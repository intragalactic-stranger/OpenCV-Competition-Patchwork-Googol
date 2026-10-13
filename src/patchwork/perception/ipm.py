"""Inverse perspective mapping: distorted camera frame -> metric bird's-eye view (BEV).

BEV convention: 1 px = `res` metres; column = (X - x_min) / res (X right), row = (y_max - Y) / res (far at
the top). Built from the *estimated* calibration plus mount height and pitch; perception never sees
the synthetic ground truth camera.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import cv2
import numpy as np

from patchwork.camera import CalibrationResult, CameraModel


@dataclass(frozen=True)
class BEVSpec:
    x_min: float = -5.0
    x_max: float = 5.0
    y_min: float = 3.0
    y_max: float = 15.0
    res: float = 0.01

    @property
    def size(self) -> tuple[int, int]:  # (width, height) for OpenCV
        return int(round((self.x_max - self.x_min) / self.res)), int(round((self.y_max - self.y_min) / self.res))

    def ground_of(self, col: np.ndarray, row: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.x_min + (col + 0.5) * self.res, self.y_max - (row + 0.5) * self.res

    def pixel_of(self, X: np.ndarray, Y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return (X - self.x_min) / self.res - 0.5, (self.y_max - Y) / self.res - 0.5


DEFAULT_BEV = BEVSpec()


def camera_from_calibration(
    cal: CalibrationResult, mount_height_m: float, pitch_deg: float, roll_deg: float = 0.0, yaw_deg: float = 0.0
) -> CameraModel:
    K, D = cal.K, cal.D
    return CameraModel(
        width=cal.image_size[0],
        height=cal.image_size[1],
        fx=float(K[0, 0]),
        fy=float(K[1, 1]),
        cx=float(K[0, 2]),
        cy=float(K[1, 2]),
        dist=tuple(float(x) for x in D[:5]),
        mount_height_m=mount_height_m,
        pitch_deg=pitch_deg,
        roll_deg=roll_deg,
        yaw_deg=yaw_deg,
    )


class IPM:
    """Precomputed remap from the *distorted* frame to the BEV for one camera pose."""

    def __init__(self, cam: CameraModel, spec: BEVSpec = DEFAULT_BEV):
        self.cam = cam
        self.spec = spec
        w, h = spec.size
        cols, rows = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
        X, Y = spec.ground_of(cols, rows)
        uv = cam.ground_to_pixel(np.stack([X.ravel(), Y.ravel()], 1), distort=True)
        self.map_x = uv[:, 0].reshape(h, w).astype(np.float32)
        self.map_y = uv[:, 1].reshape(h, w).astype(np.float32)

    def with_pose(self, pitch_deg: float, roll_deg: float = 0.0, yaw_deg: float = 0.0) -> IPM:
        return IPM(dataclasses.replace(self.cam, pitch_deg=pitch_deg, roll_deg=roll_deg, yaw_deg=yaw_deg), self.spec)

    def warp(self, frame: np.ndarray) -> np.ndarray:
        return cv2.remap(frame, self.map_x, self.map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    def warp_mask(self, mask: np.ndarray) -> np.ndarray:
        """Binary mask -> BEV, area-preserving: bilinear on a float mask, then >= 0.5."""
        f = cv2.remap(mask.astype(np.float32), self.map_x, self.map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        return f >= 0.5

    def warp_mask_box(self, mask: np.ndarray, box: tuple[int, int, int, int], pad_m: float = 0.3) -> np.ndarray:
        """Like warp_mask, but only remaps the BEV window covering the component's image bounding box
        (x, y, w, h). Identical result inside that window, ~100x cheaper for small defects."""
        x, y, w, h = box
        us = np.array([x, x + w, x, x + w, x + w / 2, x + w / 2, x, x + w], dtype=np.float64)
        vs = np.array([y, y, y + h, y + h, y, y + h, y + h / 2, y + h / 2], dtype=np.float64)
        g = self.cam.pixel_to_ground(np.stack([us, vs], 1), distorted=True)
        ok = np.isfinite(g).all(1) & (g[:, 1] > 0)
        out = np.zeros(self.map_x.shape, bool)
        if not ok.any():
            return out
        spec = self.spec
        X0, X1 = g[ok, 0].min() - pad_m, g[ok, 0].max() + pad_m
        Y0, Y1 = g[ok, 1].min() - pad_m, g[ok, 1].max() + pad_m
        c0, r1 = spec.pixel_of(np.array(X0), np.array(Y0))
        c1, r0 = spec.pixel_of(np.array(X1), np.array(Y1))
        H, W = self.map_x.shape
        r0, r1 = int(np.clip(np.floor(r0), 0, H)), int(np.clip(np.ceil(r1) + 1, 0, H))
        c0, c1 = int(np.clip(np.floor(c0), 0, W)), int(np.clip(np.ceil(c1) + 1, 0, W))
        if r1 <= r0 or c1 <= c0:
            return out
        f = cv2.remap(
            mask.astype(np.float32),
            self.map_x[r0:r1, c0:c1],
            self.map_y[r0:r1, c0:c1],
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        out[r0:r1, c0:c1] = f >= 0.5
        return out

    def ground_sampling(self, Y: float) -> tuple[float, float]:
        """Approximate size (m) of one camera pixel on the ground at range Y: (across, along)."""
        cam = self.cam
        h = cam.mount_height_m
        across = Y / cam.fx
        along = (Y * Y + h * h) / (cam.fy * h)
        return across, along
