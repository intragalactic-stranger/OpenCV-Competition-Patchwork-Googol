"""Segmentation examples through the deployed runtime (OpenCV 5 DNN): real photos (top) and synthetic dashcam
strips (bottom), including the worst cases on purpose. -> docs/midpoint/assets/seg_examples.jpg

  uv run python scripts/figures/seg_examples.py --model runs/seg-v3/model.onnx --data data/train/v2-sample
Green = ground truth outline, red fill = model prediction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from patchwork.perception.segment import Segmenter

ROOT = Path(__file__).resolve().parents[2]


def panel(img: np.ndarray, gt: np.ndarray, pred: np.ndarray, label: str, w: int = 480) -> np.ndarray:
    o = img.copy()
    o[pred] = (0.45 * o[pred] + 0.55 * np.array([0, 0, 255])).astype(np.uint8)
    cnts, _ = cv2.findContours((gt == 1).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(o, cnts, -1, (0, 255, 0), max(2, img.shape[1] // 400))
    o = cv2.resize(o, (w, int(o.shape[0] * w / o.shape[1])))
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(o, (0, 0), (tw + 10, th + 10), (0, 0, 0), -1)
    cv2.putText(o, label, (5, th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return o


def iou(gt: np.ndarray, pred: np.ndarray) -> float:
    v = gt != 255
    g, p = (gt == 1) & v, pred & v
    u = (g | p).sum()
    return float((g & p).sum() / u) if u else 1.0


def pick(seg: Segmenter, data: Path, names: list[str], k: int) -> list[np.ndarray]:
    scored = []
    for n in names:
        img = cv2.imread(str(data / "images" / f"{n}.jpg"))
        gt = cv2.imread(str(data / "masks" / f"{n}.png"), cv2.IMREAD_UNCHANGED)
        if img is None or gt is None or (gt == 1).sum() == 0:
            continue
        pred = seg.predict(img, dashcam=False).mask
        scored.append((iou(gt, pred), img, gt, pred))
    scored.sort(key=lambda x: -x[0])
    chosen = scored[: k - 1] + scored[-1:]  # best k-1 and the worst one (failure case, on purpose)
    return [
        panel(img, gt, pred, f"IoU {s:.2f}" + (" (worst)" if i == len(chosen) - 1 else ""))
        for i, (s, img, gt, pred) in enumerate(chosen)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    seg = Segmenter(args.model)
    splits = json.loads((args.data / "splits.json").read_text())
    real = pick(seg, args.data, splits["test_real"][: args.n * 6], 4)
    synth = pick(seg, args.data, splits["val_synth"][: args.n * 3], 4)

    def row(ps: list[np.ndarray]) -> np.ndarray:
        h = max(p.shape[0] for p in ps)
        return np.hstack(
            [cv2.copyMakeBorder(p, 0, h - p.shape[0], 0, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for p in ps]
        )

    r1, r2 = row(real), row(synth)
    w = max(r1.shape[1], r2.shape[1])
    pad = lambda r: cv2.copyMakeBorder(r, 0, 6, 0, w - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))  # noqa: E731
    out = ROOT / "docs" / "midpoint" / "assets" / "seg_examples.jpg"
    cv2.imwrite(str(out), np.vstack([pad(r1), pad(r2)]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"wrote {out} (engine {seg.engine})")


if __name__ == "__main__":
    main()
