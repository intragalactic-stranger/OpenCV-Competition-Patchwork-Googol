"""Camera calibration from ChArUco views (OpenCV 5 objdetect/aruco + calib modules)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import cv2
import numpy as np

from patchwork.camera import CalibrationResult

MAX_RMS_PX = 0.5
MIN_VIEWS = 10
MIN_CORNERS = 10


def charuco_board(squares=(7, 5), square_m=0.06, marker_m=0.045, dictionary=cv2.aruco.DICT_5X5_100):
    return cv2.aruco.CharucoBoard(squares, square_m, marker_m, cv2.aruco.getPredefinedDictionary(dictionary))


def calibrate(image_paths: list[Path], calibration_id: str, board=None) -> CalibrationResult:
    board = board or charuco_board()
    detector = cv2.aruco.CharucoDetector(board)
    obj_pts, img_pts, size = [], [], None
    for p in image_paths:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        size = img.shape[::-1]
        corners, ids, _, _ = detector.detectBoard(img)
        if ids is None or len(ids) < MIN_CORNERS:
            continue
        o, i = board.matchImagePoints(corners, ids)
        obj_pts.append(o)
        img_pts.append(i)
    if len(obj_pts) < MIN_VIEWS:
        raise ValueError(f"only {len(obj_pts)} usable ChArUco views (need {MIN_VIEWS})")
    rms, K, D, _, _ = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
    if rms > MAX_RMS_PX:
        raise ValueError(f"calibration rejected: RMS {rms:.3f} px > {MAX_RMS_PX}")
    return CalibrationResult(
        calibration_id,
        K,
        D.ravel(),
        size,
        float(rms),
        len(obj_pts),
        {"created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")},
    )


def save(cal: CalibrationResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "calibration_id": cal.calibration_id,
                "K": cal.K.tolist(),
                "D": cal.D.tolist(),
                "image_size": list(cal.image_size),
                "rms_px": cal.rms_px,
                "views_used": cal.views_used,
                **cal.extras,
            },
            indent=2,
        )
    )


def load(path: Path) -> CalibrationResult:
    d = json.loads(path.read_text())
    return CalibrationResult(
        d["calibration_id"],
        np.array(d["K"]),
        np.array(d["D"]),
        tuple(d["image_size"]),
        d["rms_px"],
        d["views_used"],
        {k: v for k, v in d.items() if k in ("created_at",)},
    )
