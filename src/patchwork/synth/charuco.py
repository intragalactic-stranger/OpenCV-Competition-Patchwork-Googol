"""Render ChArUco calibration views through the synthetic (distorted) camera.

Perception calibrates from these images exactly as it would from a phone's calibration session; the
true intrinsics are written separately under truth/ so they can be compared, never consumed.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from patchwork.camera import CameraModel

BOARD_SQUARES = (7, 5)
SQUARE_M = 0.06
MARKER_M = 0.045
DICT = cv2.aruco.DICT_5X5_100


def board() -> cv2.aruco.CharucoBoard:
    return cv2.aruco.CharucoBoard(BOARD_SQUARES, SQUARE_M, MARKER_M, cv2.aruco.getPredefinedDictionary(DICT))


def distort_image(ideal: np.ndarray, cam: CameraModel) -> np.ndarray:
    h, w = ideal.shape[:2]
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    pts = np.stack([xs.ravel(), ys.ravel()], axis=1).reshape(-1, 1, 2)
    und = cv2.undistortPoints(pts, cam.K, cam.D, P=cam.K).reshape(h, w, 2)
    return cv2.remap(ideal, und[..., 0], und[..., 1], cv2.INTER_LINEAR, borderValue=(235, 235, 235))


def render_views(cam: CameraModel, out_dir: Path, n_views: int = 20, seed: int = 0) -> list[Path]:
    rng = np.random.default_rng(seed)
    b = board()
    px_per_m = 4000
    sq = BOARD_SQUARES
    img = b.generateImage((int(sq[0] * SQUARE_M * px_per_m), int(sq[1] * SQUARE_M * px_per_m)), marginSize=0)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    centre = np.array([sq[0] * SQUARE_M / 2, sq[1] * SQUARE_M / 2, 0])
    for i in range(n_views):
        rvec = np.array([rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(-0.25, 0.25)])
        R, _ = cv2.Rodrigues(rvec)
        t = np.array([rng.uniform(-0.3, 0.3), rng.uniform(-0.15, 0.15), rng.uniform(0.55, 1.0)]) - R @ centre
        Hb = cam.K @ np.column_stack([R[:, 0], R[:, 1], t]) @ np.diag([1 / px_per_m, 1 / px_per_m, 1])
        ideal = cv2.warpPerspective(img, Hb, (cam.width, cam.height), borderValue=235)
        view = distort_image(cv2.cvtColor(ideal, cv2.COLOR_GRAY2BGR), cam)
        view = np.clip(view.astype(np.float32) * rng.uniform(0.8, 1.1) + rng.normal(0, 2.0, view.shape), 0, 255)
        p = out_dir / f"view_{i:02d}.png"
        cv2.imwrite(str(p), view.astype(np.uint8))
        paths.append(p)
    return paths
