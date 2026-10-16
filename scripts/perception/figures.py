"""Evidence figures for main_docs/midpoint/assets: calibration.png and bev_measure.png."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from patchwork.perception import calib  # noqa: E402
from patchwork.perception.ipm import IPM, camera_from_calibration  # noqa: E402
from patchwork.perception.measure import measure_bev, truncated_in_image  # noqa: E402
from patchwork.perception.pose import PitchEstimator  # noqa: E402

ASSETS = ROOT / "main_docs" / "midpoint" / "assets"
SYN = ROOT / "data" / "synth" / "seed07"
CAL = ROOT / "data" / "calib" / "cam01-v1.json"


def text(img, s, org, scale=1.0, th=2):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 4, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), th, cv2.LINE_AA)


def calibration_figure() -> None:
    cal = calib.load(CAL)
    truth = json.loads((SYN / "truth" / "camera.json").read_text())
    det = cv2.aruco.CharucoDetector(calib.charuco_board())
    best = None
    for p in sorted((SYN / "calib" / "charuco_cam01").glob("*.png")):
        img = cv2.imread(str(p))
        corners, ids, mk, mids = det.detectBoard(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if ids is not None and corners is not None and len(ids) == len(corners):
            if best is None or len(ids) > len(best[2]):
                best = (img, corners, ids, mk, mids)
    view, corners, ids, mk, mids = best
    cv2.aruco.drawDetectedMarkers(view, mk, mids)
    for c in corners.reshape(-1, 2):
        cv2.circle(view, (int(c[0]), int(c[1])), 7, (0, 0, 255), 2, cv2.LINE_AA)
    lines = [
        f"ChArUco calibration (OpenCV {cv2.__version__}): {cal.views_used} views, RMS {cal.rms_px:.3f} px",
        f"fx {cal.K[0, 0]:.1f} px (true {truth['fx']:.1f}, "
        f"error {abs(cal.K[0, 0] - truth['fx']) / truth['fx'] * 100:.2f}%)",
        f"k1 {cal.D[0]:+.4f} (true {truth['dist'][0]:+.4f})   k2 {cal.D[1]:+.4f} (true {truth['dist'][1]:+.4f})",
    ]
    for i, s in enumerate(lines):
        text(view, s, (30, 60 + 50 * i), 1.15)
    cv2.imwrite(str(ASSETS / "calibration.png"), cv2.resize(view, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))


def bev_figure(pass_dir: Path = SYN / "pass_1") -> None:
    cal = calib.load(CAL)
    clip = pass_dir / "clip_00"
    meta = json.loads((clip / "meta.json").read_text())
    truth = {d["index"]: d for d in json.loads((pass_dir / "truth" / "defects.json").read_text())}
    base = camera_from_calibration(cal, meta["mount_height_m"], meta["nominal_pitch_deg"])
    est = PitchEstimator(base)
    # choose the frame whose largest fully visible defect sits nearest 7.5 m ahead
    nominal = IPM(base)
    best = None
    for mp in sorted((pass_dir / "truth" / "masks").glob("clip00_*.png")):
        inst = cv2.imread(str(mp), cv2.IMREAD_UNCHANGED)
        ids = [i for i in np.unique(inst[inst > 0]) if not truncated_in_image(inst == i)]
        for i in ids:
            m = measure_bev(nominal.warp_mask(inst == i), nominal)
            if m and not m.touches_border and truth.get(int(i) - 1, {}).get("area_m2"):
                score = abs(m.centroid_y - 7.5) - 0.5 * len(ids)
                if best is None or score < best[0]:
                    best = (score, int(mp.stem.split("_")[1]), inst)
    _, fidx, inst = best
    cap = cv2.VideoCapture(str(clip / "clip.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
    ok, frame = cap.read()
    pose = est.estimate(frame)
    ipm = nominal.with_pose(pose.pitch_deg)
    bev = ipm.warp(frame)
    persp = frame.copy()
    # 1 m grid on the BEV
    w, h = ipm.spec.size
    for x in np.arange(-5, 5.01, 1.0):
        c = int(round((x - ipm.spec.x_min) / ipm.spec.res))
        cv2.line(bev, (c, 0), (c, h - 1), (255, 255, 255), 1, cv2.LINE_AA)
    for y in np.arange(3, 15.01, 1.0):
        r = int(round((ipm.spec.y_max - y) / ipm.spec.res))
        cv2.line(bev, (0, r), (w - 1, r), (255, 255, 255), 1, cv2.LINE_AA)
        text(bev, f"{y:.0f} m", (8, max(r - 6, 20)), 0.6, 1)
    for i in np.unique(inst[inst > 0]):
        t = truth.get(int(i) - 1)
        if t is None or t["area_m2"] is None:
            continue
        mask = inst == i
        cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(persp, cnts, -1, (0, 0, 255), 3)
        mb = ipm.warp_mask(mask)
        m = measure_bev(mb, ipm, truncated_in_image(mask))
        if m is None:
            continue
        cb, _ = cv2.findContours(mb.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(bev, cb, -1, (0, 0, 255), 2)
        x, y, bw, bh = cv2.boundingRect(mb.astype(np.uint8))
        label = f"{m.area_m2:.2f} m2 (true {t['area_m2']:.2f})" if not m.touches_border else "cut off: not measured"
        text(bev, label, (max(x - 40, 5), max(y - 12, 25)), 0.75, 2)
    text(persp, f"camera frame {fidx} (distorted, as recorded)", (30, 60), 1.3)
    text(bev, f"bird's-eye view, 1 cm/px, pitch {pose.pitch_deg:.2f} deg (estimated)", (10, h - 20), 0.7, 2)
    scale = persp.shape[0] / bev.shape[0]
    bev_r = cv2.resize(bev, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    fig = np.hstack([persp, bev_r])
    cv2.imwrite(str(ASSETS / "bev_measure.png"), cv2.resize(fig, None, fx=0.55, fy=0.55, interpolation=cv2.INTER_AREA))
    print("bev frame", fidx, "pitch", round(pose.pitch_deg, 3))


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    calibration_figure()
    bev_figure()
    print("written:", ASSETS / "calibration.png", ASSETS / "bev_measure.png")
