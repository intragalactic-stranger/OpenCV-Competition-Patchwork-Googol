"""Damage segmentation in OpenCV 5's DNN module (stage [5]).

The model sees the *road strip* of a 1080p dashcam frame (rows 400-912, the measurement band plus margin)
resized to 960x256, exactly as in training (training/prepare.py). Any other image is resized to width 960.
Engine order (decision D-15): ENGINE_NEW -> ENGINE_ORT -> ENGINE_CLASSIC; the engine used is recorded.
Output: damage probability at full frame resolution (0 outside the strip) -> binary mask after cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MEAN = np.array([0.485, 0.456, 0.406], np.float32) * 255
STD = np.array([0.229, 0.224, 0.225], np.float32) * 255
STRIP = (400, 912)
STRIP_SIZE = (960, 256)
ENGINE_ORDER = (("ENGINE_NEW", 2), ("ENGINE_ORT", 4), ("ENGINE_CLASSIC", 1))


def preprocess(bgr: np.ndarray, width: int = 960) -> np.ndarray:
    """BGR uint8 -> NCHW float32 (RGB, ImageNet mean/std), width 960, H padded to a multiple of 32."""
    s = width / bgr.shape[1]
    h = int(round(bgr.shape[0] * s))
    img = cv2.resize(bgr, (width, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    img = cv2.copyMakeBorder(img, 0, (32 - h % 32) % 32, 0, 0, cv2.BORDER_CONSTANT, value=0)
    rgb = (img[..., ::-1].astype(np.float32) - MEAN) / STD
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])


@dataclass
class Segmentation:
    prob: np.ndarray  # (H, W) float32 damage probability, frame resolution
    mask: np.ndarray  # (H, W) bool after threshold + morphology
    engine: str


class Segmenter:
    def __init__(self, model_path: Path, threshold: float = 0.5, min_px: int = 150, engine: str | None = None):
        self.threshold, self.min_px = threshold, min_px
        order = [e for e in ENGINE_ORDER if engine is None or e[0] == engine]
        errors = []
        for name, code in order:
            try:
                net = cv2.dnn.readNetFromONNX(str(model_path), code)
                net.setInput(preprocess(np.zeros((256, 960, 3), np.uint8)))
                net.forward()
                self.net, self.engine = net, name
                break
            except Exception as e:  # noqa: BLE001 - any engine failure means "try the next one"
                errors.append(f"{name}: {str(e).splitlines()[0][:200] if str(e) else type(e).__name__}")
        else:
            raise RuntimeError("no OpenCV DNN engine could run the model: " + "; ".join(errors))

    def _prob(self, img: np.ndarray) -> np.ndarray:
        blob = preprocess(img)
        self.net.setInput(blob)
        logits = self.net.forward()[0]  # (C, h, w) at 1/4 (SegFormer) or full input resolution
        e = np.exp(logits - logits.max(0, keepdims=True))
        p = (e[1] / e.sum(0)).astype(np.float32)
        h_in = int(round(img.shape[0] * 960 / img.shape[1]))
        p = cv2.resize(p, (blob.shape[3], blob.shape[2]), interpolation=cv2.INTER_LINEAR)[:h_in]
        return cv2.resize(p, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)

    def predict(self, bgr: np.ndarray, dashcam: bool = True) -> Segmentation:
        if dashcam and bgr.shape[:2] == (1080, 1920):
            prob = np.zeros(bgr.shape[:2], np.float32)
            prob[STRIP[0] : STRIP[1]] = self._prob(bgr[STRIP[0] : STRIP[1]])
        else:
            prob = self._prob(bgr)
        mask = (prob >= self.threshold).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        keep = np.zeros(n, bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= self.min_px
        return Segmentation(prob, keep[lab], self.engine)
