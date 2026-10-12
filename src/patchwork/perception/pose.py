"""Per-frame camera pitch (and yaw) from lane-line geometry on the road plane.

Line segments (lane paint, kerb edges) are detected once in the image. Their endpoints are projected
onto the road plane under candidate pitches. On the plane, longitudinal lines must be parallel:
  - a pitch error makes them *fan* (angle grows with lateral position x): angle = a + b*x with b != 0
  - a yaw offset tilts them *all the same way*: constant a
So the pitch is where the fan coefficient b crosses zero; -a is then the yaw. Cheap: only segment
endpoints are re-projected per candidate, not images.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import cv2
import numpy as np

from patchwork.camera import CameraModel


@dataclass
class PoseEstimate:
    pitch_deg: float
    yaw_deg: float
    n_segments: int
    confidence: float  # 0..1: enough segments on both sides and a clean zero crossing
    used: bool  # False -> caller should fall back to the nominal pitch


class PitchEstimator:
    def __init__(
        self,
        cam: CameraModel,
        span_deg: float = 1.5,
        step_deg: float = 0.1,
        y_range: tuple[float, float] = (4.0, 30.0),
        min_segments: int = 4,
    ):
        self.cam = cam
        self.nominal = cam.pitch_deg
        self.deltas = np.arange(-span_deg, span_deg + 1e-9, step_deg)
        self.Hs = [dataclasses.replace(cam, pitch_deg=cam.pitch_deg + d).H_image_to_ground for d in self.deltas]
        self.y_range = y_range
        self.min_segments = min_segments
        v_h = cam.horizon_v()
        self.roi_top = int(max(v_h + 25, 0))
        self.roi_bottom = cam.height - 110  # above the bonnet

    def _segments(self, gray: np.ndarray) -> np.ndarray:
        roi = gray[self.roi_top : self.roi_bottom]
        edges = cv2.Canny(cv2.GaussianBlur(roi, (5, 5), 0), 40, 120)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40, minLineLength=40, maxLineGap=8)
        if lines is None:
            return np.zeros((0, 4))
        seg = lines.reshape(-1, 4).astype(np.float64)
        seg[:, [1, 3]] += self.roi_top
        # drop near-horizontal segments (seams, shadows' edges): longitudinal lines are steep in the image
        ang = np.degrees(np.arctan2(np.abs(seg[:, 3] - seg[:, 1]), np.abs(seg[:, 2] - seg[:, 0])))
        return seg[ang > 15]

    def _fan(self, H: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> tuple[float, float, int]:
        def proj(p):
            g = np.column_stack([p, np.ones(len(p))]) @ H.T
            return g[:, :2] / g[:, 2:3]

        g0, g1 = proj(p0), proj(p1)
        y_mid = (g0[:, 1] + g1[:, 1]) / 2
        dx, dy = g1[:, 0] - g0[:, 0], g1[:, 1] - g0[:, 1]
        length = np.hypot(dx, dy)
        sign = np.where(dy < 0, -1.0, 1.0)  # orient every segment forward
        theta = np.arctan2(dx * sign, dy * sign)
        x_mid = (g0[:, 0] + g1[:, 0]) / 2
        ok = (y_mid > self.y_range[0]) & (y_mid < self.y_range[1]) & (np.abs(theta) < math.radians(25)) & (length > 0.4)
        if ok.sum() < self.min_segments or np.ptp(x_mid[ok]) < 2.0:
            return math.nan, math.nan, int(ok.sum())
        w = length[ok]
        A = np.column_stack([np.ones(ok.sum()), x_mid[ok]])
        coef, *_ = np.linalg.lstsq(A * w[:, None], theta[ok] * w, rcond=None)
        return float(coef[0]), float(coef[1]), int(ok.sum())

    def estimate(self, frame_bgr: np.ndarray) -> PoseEstimate:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
        seg = self._segments(gray)
        if len(seg) < self.min_segments:
            return PoseEstimate(self.nominal, 0.0, len(seg), 0.0, False)
        cam = self.cam
        p0 = cv2.undistortPoints(seg[:, :2].reshape(-1, 1, 2), cam.K, cam.D, P=cam.K).reshape(-1, 2)
        p1 = cv2.undistortPoints(seg[:, 2:].reshape(-1, 1, 2), cam.K, cam.D, P=cam.K).reshape(-1, 2)
        res = [self._fan(H, p0, p1) for H in self.Hs]
        b = np.array([r[1] for r in res])
        a = np.array([r[0] for r in res])
        n = max(r[2] for r in res)
        finite = np.isfinite(b)
        if finite.sum() < 3:
            return PoseEstimate(self.nominal, 0.0, n, 0.0, False)
        d, bb, aa = self.deltas[finite], b[finite], a[finite]
        cross = np.where(np.sign(bb[:-1]) != np.sign(bb[1:]))[0]
        if len(cross) == 0:
            return PoseEstimate(self.nominal, 0.0, n, 0.0, False)
        # zero crossing nearest to the nominal pitch, linearly interpolated
        j = cross[np.argmin(np.abs(d[cross]))]
        t = bb[j] / (bb[j] - bb[j + 1])
        delta = d[j] + t * (d[j + 1] - d[j])
        yaw = -math.degrees(aa[j] + t * (aa[j + 1] - aa[j]))
        conf = float(min(1.0, n / 12) * (1.0 if len(cross) == 1 else 0.5))
        return PoseEstimate(self.nominal + float(delta), yaw, n, conf, True)
