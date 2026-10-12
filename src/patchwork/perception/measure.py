"""Metric measurement of defect masks on the bird's-eye view, with per-frame fusion."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from patchwork.perception.ipm import IPM

# best-resolved range band for measurement (m ahead of the camera)
MEASURE_Y = (4.0, 12.0)


@dataclass
class FrameMeasurement:
    area_m2: float
    length_m: float
    width_m: float
    centroid_x: float  # m, + right
    centroid_y: float  # m ahead
    uncertainty_m2: float
    touches_border: bool


def truncated_in_image(mask: np.ndarray, margin: int = 3, bottom_px: int = 100) -> bool:
    """True if a perspective-view mask is cut by the image edge or the car bonnet (bottom band)."""
    h, w = mask.shape
    return bool(
        mask[:, :margin].any() or mask[:, w - margin :].any() or mask[:margin].any() or mask[h - bottom_px :].any()
    )


def measure_bev(mask_bev: np.ndarray, ipm: IPM, truncated: bool = False) -> FrameMeasurement | None:
    n = int(mask_bev.sum())
    if n == 0:
        return None
    spec = ipm.spec
    ys, xs = np.nonzero(mask_bev)
    X, Y = spec.ground_of(xs.astype(np.float64), ys.astype(np.float64))
    area = n * spec.res * spec.res
    pts = np.stack([xs, ys], 1).astype(np.float32)
    (_, _), (a, b), _ = cv2.minAreaRect(pts)
    length, width = max(a, b) * spec.res, min(a, b) * spec.res
    # uncertainty: a one-camera-pixel band around the perimeter, at the defect's range
    cnts, _ = cv2.findContours(mask_bev.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    perim = sum(cv2.arcLength(c, True) for c in cnts) * spec.res
    across, along = ipm.ground_sampling(float(Y.mean()))
    unc = 0.5 * perim * (across + along) / 2
    h, w = mask_bev.shape
    border = truncated or bool(mask_bev[0].any() or mask_bev[-1].any() or mask_bev[:, 0].any() or mask_bev[:, -1].any())
    return FrameMeasurement(area, length, width, float(X.mean()), float(Y.mean()), unc, border)


def fuse(measurements: list[FrameMeasurement]) -> FrameMeasurement | None:
    """Median over frames whose defect sits fully inside the BEV and in the best-resolved range band."""
    good = [m for m in measurements if not m.touches_border and MEASURE_Y[0] <= m.centroid_y <= MEASURE_Y[1]]
    if not good:
        return None
    a = np.array([m.area_m2 for m in good])
    i = int(np.argsort(a)[len(a) // 2])
    best = good[i]
    spread = float(np.percentile(a, 75) - np.percentile(a, 25)) if len(a) >= 3 else 0.0
    return FrameMeasurement(
        float(np.median(a)),
        float(np.median([m.length_m for m in good])),
        float(np.median([m.width_m for m in good])),
        best.centroid_x,
        best.centroid_y,
        float(np.hypot(best.uncertainty_m2, spread / 2)),
        False,
    )
