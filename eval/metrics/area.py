"""Damaged-area accuracy against exact synthetic ground truth.

--oracle : feed the TRUE perspective masks through our geometry (calibration -> IPM -> BEV area).
           Isolates geometry error from segmentation error (target: MAPE <= 5%).
Two pose modes are reported:
  true_pose       per-frame TRUE pitch/roll/yaw (calibration + resampling error only)
  nominal_pose    fixed nominal pitch (no pose refinement)
  estimated_pose  per-frame pitch estimated from lane-line geometry (perception/pose.py): the real pipeline
  no_rectification  ABLATION: mask pixel count x one fixed m²/pixel scale (the ground area of one pixel at 8 m,
                  the middle of the measurement band), i.e. measuring in the camera image without the bird's-eye
                  view. Same masks, same frames, same median fusion: only the homography is taken away

Usage: uv run python -m eval.metrics.area --oracle data/synth/seed07/pass_1 [--calib data/calib/cam01-v1.json]
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from patchwork.perception import calib as calib_mod
from patchwork.perception.ipm import IPM, camera_from_calibration
from patchwork.perception.measure import fuse, measure_bev, truncated_in_image
from patchwork.perception.pose import PitchEstimator

ROOT = Path(__file__).resolve().parents[2]


def load_frames(clip_dir: Path) -> dict[int, dict]:
    with open(clip_dir / "frames.csv") as f:
        return {int(r["frame"]): {k: float(v) for k, v in r.items() if v != ""} for r in csv.DictReader(f)}


def run(pass_dir: Path, cal_path: Path, pitch_bins: int = 40) -> dict:
    cal = calib_mod.load(cal_path)
    truth = {d["index"]: d for d in json.loads((pass_dir / "truth" / "defects.json").read_text())}
    per_mode: dict[str, dict[int, list]] = {
        m: defaultdict(list) for m in ("true_pose", "nominal_pose", "estimated_pose")
    }
    ipm_cache: dict[tuple, IPM] = {}
    flat: dict[int, list[float]] = defaultdict(list)  # no_rectification ablation
    for clip_dir in sorted(pass_dir.glob("clip_*")):
        meta = json.loads((clip_dir / "meta.json").read_text())
        frames = load_frames(clip_dir)
        base = camera_from_calibration(cal, meta["mount_height_m"], meta["nominal_pitch_deg"])
        nominal = ipm_cache.setdefault(("nominal",), IPM(base))
        estimator = PitchEstimator(base)
        # one fixed scale: ground area of one pixel at the band centre (8 m ahead, on the optical axis)
        sq = np.array([[-0.05, 7.95], [0.05, 7.95], [0.05, 8.05], [-0.05, 8.05]])
        k_m2_per_px = 0.01 / cv2.contourArea(base.ground_to_pixel(sq, distort=True).astype(np.float32))
        tag = clip_dir.name.split("_")[1]
        masks = {int(mp.stem.split("_")[1]): mp for mp in (pass_dir / "truth" / "masks").glob(f"clip{tag}_*.png")}
        cap = cv2.VideoCapture(str(clip_dir / "clip.mp4"))
        for fidx in range(max(masks) + 1 if masks else 0):
            ok, frame = cap.read()
            if not ok:
                break
            if fidx not in masks:
                continue
            mp = masks[fidx]
            fr = frames[fidx]
            est = estimator.estimate(frame)
            ekey = (round(est.pitch_deg, 2), 0.0, 0.0)
            if ekey not in ipm_cache:
                ipm_cache[ekey] = nominal.with_pose(*ekey)
            # quantise the true pose a little so IPMs can be cached (0.01 deg is far below any effect)
            key = (round(fr["pitch_deg"], 2), round(fr["roll_deg"], 2), round(fr["yaw_deg"], 2))
            if key not in ipm_cache:
                ipm_cache[key] = nominal.with_pose(*key)
            inst = cv2.imread(str(mp), cv2.IMREAD_UNCHANGED)
            for iid in np.unique(inst[inst > 0]):
                mask = inst == iid
                cut = truncated_in_image(mask)
                for mode, ipm in (
                    ("true_pose", ipm_cache[key]),
                    ("nominal_pose", nominal),
                    ("estimated_pose", ipm_cache[ekey]),
                ):
                    m = measure_bev(ipm.warp_mask(mask), ipm, truncated=cut)
                    if m:
                        per_mode[mode][int(iid) - 1].append(m)
                        if mode == "nominal_pose":  # same frames the pipeline would measure
                            flat[int(iid) - 1].append(float(mask.sum()) * k_m2_per_px)
    out = {}
    rows = []
    for idx, vals in flat.items():
        t = truth.get(idx)
        if t is None or t["area_m2"] is None:
            continue
        a = float(np.median(vals))
        rows.append(
            {
                "truth_id": t["truth_id"],
                "kind": t["kind"],
                "true_m2": t["area_m2"],
                "meas_m2": a,
                "err_pct": 100 * (a - t["area_m2"]) / t["area_m2"],
                "frames": len(vals),
            }
        )
    if rows:
        errs = np.array([abs(r["err_pct"]) for r in rows])
        out["no_rectification"] = {
            "n_measured": len(rows),
            "mape_pct": round(float(errs.mean()), 2),
            "median_ape_pct": round(float(np.median(errs)), 2),
            "bias_pct": round(float(np.mean([r["err_pct"] for r in rows])), 2),
            "p90_ape_pct": round(float(np.percentile(errs, 90)), 2),
            "rows": rows,
        }
    for mode, per in per_mode.items():
        rows = []
        for idx, ms in per.items():
            t = truth.get(idx)
            if t is None or t["area_m2"] is None:
                continue
            f = fuse(ms)
            if f is None:
                continue
            rows.append(
                {
                    "truth_id": t["truth_id"],
                    "kind": t["kind"],
                    "true_m2": t["area_m2"],
                    "meas_m2": f.area_m2,
                    "unc_m2": f.uncertainty_m2,
                    "err_pct": 100 * (f.area_m2 - t["area_m2"]) / t["area_m2"],
                    "frames": len(ms),
                    "y": f.centroid_y,
                }
            )
        errs = np.array([abs(r["err_pct"]) for r in rows])
        bias = np.array([r["err_pct"] for r in rows])
        by_kind = {
            k: round(float(np.mean([abs(r["err_pct"]) for r in rows if r["kind"] == k])), 2)
            for k in sorted({r["kind"] for r in rows})
        }
        within = float(np.mean([abs(r["meas_m2"] - r["true_m2"]) <= 2 * r["unc_m2"] for r in rows])) if rows else 0
        out[mode] = {
            "n_measured": len(rows),
            "n_truth_visible": len(per),
            "mape_pct": round(float(errs.mean()), 2) if rows else None,
            "median_ape_pct": round(float(np.median(errs)), 2) if rows else None,
            "bias_pct": round(float(bias.mean()), 2) if rows else None,
            "p90_ape_pct": round(float(np.percentile(errs, 90)), 2) if rows else None,
            "mape_by_kind": by_kind,
            "within_2sigma": round(within, 3),
            "rows": rows,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_dirs", nargs="+", type=Path)
    ap.add_argument("--oracle", action="store_true", required=True, help="(model-mask mode arrives in Phase 3)")
    ap.add_argument("--calib", type=Path, default=ROOT / "data" / "calib" / "cam01-v1.json")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "area_oracle.json")
    args = ap.parse_args()
    merged: dict[str, dict] = {}
    for pd in args.pass_dirs:
        res = run(pd, args.calib)
        for mode, r in res.items():
            m = merged.setdefault(mode, {"rows": []})
            m["rows"] += r["rows"]
    summary = {}
    for mode, m in merged.items():
        rows = m["rows"]
        e = np.array([abs(r["err_pct"]) for r in rows])
        summary[mode] = {
            "n": len(rows),
            "mape_pct": round(float(e.mean()), 2),
            "median_ape_pct": round(float(np.median(e)), 2),
            "p90_ape_pct": round(float(np.percentile(e, 90)), 2),
            "bias_pct": round(float(np.mean([r["err_pct"] for r in rows])), 2),
            "within_2sigma": round(
                float(np.mean([abs(r["meas_m2"] - r["true_m2"]) <= 2 * r.get("unc_m2", 0) for r in rows])), 3
            ),
        }
        sm = summary[mode]
        print(
            f"{mode:14s} n={len(rows):3d}  MAPE {sm['mape_pct']:5.2f}%  median {sm['median_ape_pct']:5.2f}%  "
            f"p90 {sm['p90_ape_pct']:5.2f}%  bias {sm['bias_pct']:+5.2f}%  within 2σ {sm['within_2sigma']:.0%}"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "detail": merged}, indent=1))


if __name__ == "__main__":
    main()
