"""Privacy: blur faces and number plates before any frame is stored or sent anywhere (stage [2]).

Faces: YuNet (OpenCV Zoo, `cv2.FaceDetectorYN`) on a <= 640 px copy, boxes grown by 20 %.
Plates: no licence-clean open plate detector exists for Indian plates, so we use a classical detector:
dark character-shaped blobs (adaptive threshold) of similar height, aligned in a row (>= 5 characters)
on a plain lighter background -> one text box. This blurs any legible text line (plates, shop signs),
which is the safe direction. Every blurred region is recorded so measurement can flag overlaps.

Downstream code takes a `BlurredFrame`, never a raw array, so "blur before write" is enforced by type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
YUNET = ROOT / "data" / "models" / "face_detection_yunet_2023mar.onnx"


@dataclass(frozen=True)
class Region:
    kind: str  # "face" | "plate"
    box: tuple[int, int, int, int]  # x, y, w, h in full-resolution pixels
    score: float


@dataclass(frozen=True)
class BlurredFrame:
    image: np.ndarray
    regions: tuple[Region, ...] = field(default_factory=tuple)

    def overlaps(self, box: tuple[int, int, int, int]) -> bool:
        x, y, w, h = box
        return any(
            not (rx >= x + w or rx + rw <= x or ry >= y + h or ry + rh <= y)
            for rx, ry, rw, rh in (r.box for r in self.regions)
        )


def _grow(box: np.ndarray, frac: float, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = box
    x0, y0 = max(int(x - frac * w), 0), max(int(y - frac * h), 0)
    x1, y1 = min(int(x + w * (1 + frac)), shape[1]), min(int(y + h * (1 + frac)), shape[0])
    return x0, y0, max(x1 - x0, 0), max(y1 - y0, 0)


def blur_region(img: np.ndarray, box: tuple[int, int, int, int]) -> None:
    """Irreversible: pixelate to 6 px cells then Gaussian blur, in place."""
    x, y, w, h = box
    if w < 2 or h < 2:
        return
    roi = img[y : y + h, x : x + w]
    small = cv2.resize(roi, (max(w // 6, 1), max(h // 6, 1)), interpolation=cv2.INTER_AREA)
    roi[:] = cv2.GaussianBlur(cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST), (0, 0), max(w, h) / 12)


def _dedupe(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Drop near-duplicate boxes."""
    keep: list[tuple[int, int, int, int]] = []
    for b in sorted(boxes, key=lambda b: -b[2] * b[3]):
        x, y, w, h = b
        if not any(
            abs(x - k[0]) <= 0.25 * k[2] + 1 and abs(y - k[1]) <= 0.25 * k[3] + 1 and abs(h - k[3]) <= 0.3 * k[3] + 1
            for k in keep
        ):
            keep.append(b)
    return keep


def find_plates(bgr: np.ndarray, work_w: int = 1920, min_chars: int = 5) -> list[Region]:
    """Character-row detector: dark blobs of character shape and similar height, aligned in a row."""
    s = min(work_w / bgr.shape[1], 1.0)
    gray = cv2.cvtColor(cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    # dark strokes on a lighter local background -> connected components of character size
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 12)
    n, _, stats, _ = cv2.connectedComponentsWithStats(th, connectivity=8)
    chars = [
        (int(x), int(y), int(w), int(h))
        for x, y, w, h, a in stats[1:]
        if 6 <= h <= 40 and 0.15 <= w / h <= 3.5 and 0.15 <= a / (w * h) <= 0.85
    ]

    def n_chars(b: tuple[int, int, int, int]) -> int:  # touching characters merge into one wide blob
        return max(1, round(b[2] / (0.6 * b[3])))

    chars = sorted(_dedupe(chars), key=lambda b: b[0])
    used = [False] * len(chars)
    out = []
    for i, (x, y, w, h) in enumerate(chars):
        if used[i]:
            continue
        row, last = [i], (x, y, w, h)
        for j in range(i + 1, len(chars)):
            xj, yj, wj, hj = chars[j]
            lx, ly, lw, lh = last
            if xj - (lx + lw) > 1.2 * lh:
                break
            if xj <= lx or not (0.75 <= hj / lh <= 1.33) or abs((yj + hj / 2) - (ly + lh / 2)) > 0.3 * lh:
                continue
            row.append(j)
            last = chars[j]
        xs = [chars[k] for k in row]
        if sum(n_chars(b) for b in xs) < min_chars or len(row) < 3:
            continue
        x0, y0 = min(b[0] for b in xs), min(b[1] for b in xs)
        x1, y1 = max(b[0] + b[2] for b in xs), max(b[1] + b[3] for b in xs)
        if not 2.0 <= (x1 - x0) / max(y1 - y0, 1) <= 12.0:
            continue
        # printed text sits on a plain, clearly lighter background; cracks and texture do not
        patch = gray[y0:y1, x0:x1]
        ink = th[y0:y1, x0:x1] > 0
        if ink.all() or not ink.any():
            continue
        bg, fg = patch[~ink], patch[ink]
        if float(bg.mean()) - float(fg.mean()) < 60 or float(bg.std()) > 30:
            continue
        for k in row:
            used[k] = True
        box = np.array([x0, y0, x1 - x0, y1 - y0], dtype=np.float64) / s
        out.append(Region("plate", tuple(int(v) for v in box), float(min(sum(n_chars(b) for b in xs) / 10, 1.0))))
    return out


class Privacy:
    def __init__(self, yunet_path: Path = YUNET, face_score: float = 0.6, plates: bool = True):
        self.det = cv2.FaceDetectorYN.create(str(yunet_path), "", (320, 320), face_score, 0.3, 5000)
        self.plates = plates

    def faces(self, bgr: np.ndarray) -> list[Region]:
        h, w = bgr.shape[:2]
        s = min(640 / w, 1.0)
        small = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr
        self.det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.det.detect(small)
        if faces is None:
            return []
        return [Region("face", tuple(int(v) for v in f[:4] / s), float(f[-1])) for f in faces]

    def apply(self, bgr: np.ndarray) -> BlurredFrame:
        img = bgr.copy()
        regions = self.faces(bgr) + (find_plates(bgr) if self.plates else [])
        grown = []
        for r in regions:
            box = _grow(np.array(r.box, dtype=np.float64), 0.2, img.shape[:2])
            blur_region(img, box)
            grown.append(Region(r.kind, box, r.score))
        return BlurredFrame(img, tuple(grown))
