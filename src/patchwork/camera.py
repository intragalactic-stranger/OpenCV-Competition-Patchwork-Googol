"""Pinhole + Brown-Conrady camera mounted on a vehicle, and the road-plane homography.

Shared by the synthetic renderer (to draw the road) and by perception (to undo it), so both sides
agree on one definition of geometry.

Frames
  vehicle : X right, Y forward, Z up; origin on the road surface directly below the camera.
  camera  : OpenCV convention, x right, y down, z forward (optical axis).
  pitch   : positive = camera tilted down towards the road.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

# vehicle axes -> camera axes for a level camera looking forward
_B = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])


@dataclass(frozen=True)
class CameraModel:
    width: int = 1920
    height: int = 1080
    fx: float = 1400.0
    fy: float = 1400.0
    cx: float = 960.0
    cy: float = 540.0
    dist: tuple[float, ...] = (-0.28, 0.08, 0.0005, -0.0003, 0.0)  # k1 k2 p1 p2 k3
    mount_height_m: float = 1.30
    pitch_deg: float = 8.0
    roll_deg: float = 0.0
    yaw_deg: float = 0.0  # heading of the camera relative to the road direction (+ = turned right)
    camera_id: str = "cam01"

    # ----- intrinsics -----------------------------------------------------------------------
    @property
    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]])

    @property
    def D(self) -> np.ndarray:
        return np.array(self.dist, dtype=np.float64)

    # ----- extrinsics -----------------------------------------------------------------------
    @property
    def R(self) -> np.ndarray:
        """Rotation road-aligned vehicle frame -> camera."""
        p, r, y = math.radians(self.pitch_deg), math.radians(self.roll_deg), math.radians(self.yaw_deg)
        rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
        rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
        # yaw about the vehicle's up axis (applied in the vehicle frame, before the axis swap)
        ry = np.array([[math.cos(y), math.sin(y), 0], [-math.sin(y), math.cos(y), 0], [0, 0, 1]])
        return rz @ rx @ _B @ ry

    @property
    def H_ground_to_image(self) -> np.ndarray:
        """Homography (X, Y, 1) on the road plane [m] -> undistorted pixel (u, v, 1)."""
        M = self.R @ np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -self.mount_height_m]])
        return self.K @ M

    @property
    def H_image_to_ground(self) -> np.ndarray:
        return np.linalg.inv(self.H_ground_to_image)

    def horizon_v(self) -> float:
        """Image row of the horizon (undistorted), ignoring roll."""
        return self.cy - self.fy * math.tan(math.radians(self.pitch_deg))

    # ----- projections ----------------------------------------------------------------------
    def ground_to_pixel(self, XY: np.ndarray, distort: bool = True) -> np.ndarray:
        """(N,2) road-plane metres -> (N,2) pixels (distorted by default)."""
        XY = np.asarray(XY, dtype=np.float64).reshape(-1, 2)
        P = np.column_stack([XY, np.zeros(len(XY))])
        P_cam = (self.R @ (P - np.array([0.0, 0.0, self.mount_height_m])).T).T
        if not distort:
            uvw = (self.K @ P_cam.T).T
            return uvw[:, :2] / uvw[:, 2:3]
        uv, _ = cv2.projectPoints(P_cam, np.zeros(3), np.zeros(3), self.K, self.D)
        return uv.reshape(-1, 2)

    def pixel_to_ground(self, uv: np.ndarray, distorted: bool = True) -> np.ndarray:
        """(N,2) pixels -> (N,2) road-plane metres. Pixels above the horizon give Y < 0 (invalid)."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 1, 2)
        if distorted:
            uv = cv2.undistortPoints(uv, self.K, self.D, P=self.K)
        uv = uv.reshape(-1, 2)
        g = (self.H_image_to_ground @ np.column_stack([uv, np.ones(len(uv))]).T).T
        return g[:, :2] / g[:, 2:3]

    def ground_lookup(self, distorted: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Per-pixel road-plane coordinates for the whole image: X, Y (float32, metres) and a mask of
        pixels that actually see the road ahead (below the horizon)."""
        us, vs = np.meshgrid(np.arange(self.width, dtype=np.float64), np.arange(self.height, dtype=np.float64))
        pts = np.stack([us.ravel(), vs.ravel()], axis=1)
        if distorted:
            pts = cv2.undistortPoints(pts.reshape(-1, 1, 2), self.K, self.D, P=self.K).reshape(-1, 2)
        g = (self.H_image_to_ground @ np.column_stack([pts, np.ones(len(pts))]).T).T
        w = g[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            X = (g[:, 0] / w).reshape(self.height, self.width)
            Y = (g[:, 1] / w).reshape(self.height, self.width)
        # rays above the horizon meet the plane behind the camera, i.e. Y <= 0
        valid = np.isfinite(Y) & (Y > 0)
        return X.astype(np.float32), Y.astype(np.float32), valid

    def undistorted_pixel_grid(self) -> np.ndarray:
        """(H*W, 3) homogeneous *undistorted* pixel coordinates for every distorted image pixel.
        Pose-independent, so compute once and reuse with `ground_from_grid` for each frame."""
        us, vs = np.meshgrid(np.arange(self.width, dtype=np.float64), np.arange(self.height, dtype=np.float64))
        pts = np.stack([us.ravel(), vs.ravel()], axis=1).reshape(-1, 1, 2)
        und = cv2.undistortPoints(pts, self.K, self.D, P=self.K).reshape(-1, 2)
        return np.column_stack([und, np.ones(len(und))]).astype(np.float32)

    def ground_from_grid(self, grid: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Road-plane X, Y (H, W float32) and validity for this pose, from `undistorted_pixel_grid`."""
        Hi = self.H_image_to_ground.astype(np.float32)
        g = grid @ Hi.T
        with np.errstate(divide="ignore", invalid="ignore"):
            X = (g[:, 0] / g[:, 2]).reshape(self.height, self.width)
            Y = (g[:, 1] / g[:, 2]).reshape(self.height, self.width)
        valid = np.isfinite(Y) & (Y > 0)
        return X, Y, valid

    def ray_dirs_from_grid(self, grid: np.ndarray) -> np.ndarray:
        """(H*W, 3) unit-free ray directions in the road-aligned vehicle frame for each pixel."""
        cam = grid @ np.linalg.inv(self.K).T.astype(np.float32)
        return cam @ self.R.astype(np.float32)  # R is orthonormal: vehicle = R^T cam

    # ----- io --------------------------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> CameraModel:
        d = json.loads(text)
        d["dist"] = tuple(d["dist"])
        return cls(**d)

    def save(self, path: Path) -> None:
        path.write_text(self.to_json())


@dataclass
class CalibrationResult:
    """What perception gets back from ChArUco calibration (the truth is never used by perception)."""

    calibration_id: str
    K: np.ndarray
    D: np.ndarray
    image_size: tuple[int, int]
    rms_px: float
    views_used: int
    extras: dict = field(default_factory=dict)
