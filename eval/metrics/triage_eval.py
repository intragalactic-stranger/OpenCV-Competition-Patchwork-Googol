"""Frame-triage evaluation against synthetic truth.

For each clip: run triage on the video, then use the TRUE per-frame chainage (frames.csv) to check
  - odometry: estimated distance vs true distance, per-step error, stop detection
  - recall loss: a defect counts as *covered* if its centroid lies in the 4-12 m measurement band of at
    least one frame. Recall loss = covered by all frames but by no kept frame. We also report the share
    covered by >= 2 kept frames (what multi-frame fusion wants).
  - keep rate (% of 15 fps frames) and kept frames per km.

Usage: uv run python -m eval.metrics.triage_eval data/synth/seed07/pass_1 [--calib data/calib/cam01-v1.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from patchwork.perception import calib as calib_mod
from patchwork.perception.ipm import camera_from_calibration
from patchwork.perception.measure import MEASURE_Y
from patchwork.perception.triage import TriageConfig, triage_video

ROOT = Path(__file__).resolve().parents[2]


def coverage(s_frames: np.ndarray, frame_idx: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Number of frames (from frame_idx) whose measurement band contains each defect centroid."""
    ahead = centroids[None, :] - s_frames[frame_idx][:, None]
    return ((ahead >= MEASURE_Y[0]) & (ahead <= MEASURE_Y[1])).sum(0)


def run_clip(clip_dir: Path, defects: list[dict], cal_path: Path, cfg: TriageConfig) -> dict:
    meta = json.loads((clip_dir / "meta.json").read_text())
    cam = camera_from_calibration(calib_mod.load(cal_path), meta["mount_height_m"], meta["nominal_pitch_deg"])
    t0 = time.time()
    res = triage_video(str(clip_dir / "clip.mp4"), cam, meta["fps"], cfg)
    secs = time.time() - t0
    with open(clip_dir / "frames.csv") as f:
        s = np.array([float(r["s"]) for r in csv.DictReader(f)])[: len(res.scores)]
    lo, hi = s.min(), s.max()
    cents = np.array([d["centroid_s"] for d in defects if lo <= d["centroid_s"] <= hi + MEASURE_Y[1]])
    true_step = np.diff(s, prepend=s[0])
    est_step = np.array([x.travel_m for x in res.scores])
    moving = true_step > 0.2
    stopped = true_step < 0.05
    all_cov = coverage(s, np.arange(len(s)), cents) if len(cents) else np.zeros(0)
    kept_cov = coverage(s, np.array(res.kept, dtype=int), cents) if len(cents) else np.zeros(0)
    seen = all_cov > 0
    return {
        "clip": clip_dir.name,
        **res.summary(),
        "true_distance_m": round(float(s[-1] - s[0]), 1),
        "odometry_err_pct": round(100 * (res.distance_m - (s[-1] - s[0])) / max(s[-1] - s[0], 1e-6), 2),
        "step_abs_err_median_pct": round(
            100 * float(np.median(np.abs(est_step[moving] - true_step[moving]) / true_step[moving])), 2
        ),
        "stopped_frames": int(stopped.sum()),
        "stopped_detected_pct": round(100 * float((est_step[stopped] == 0).mean()), 1) if stopped.any() else None,
        "defects_covered_all": int(seen.sum()),
        "defects_covered_kept": int((kept_cov[seen] > 0).sum()),
        "defects_covered_kept_2plus": int((kept_cov[seen] >= 2).sum()),
        "ms_per_frame": round(1000 * secs / max(len(res.scores), 1), 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_dirs", nargs="+", type=Path)
    ap.add_argument("--calib", type=Path, default=ROOT / "data" / "calib" / "cam01-v1.json")
    ap.add_argument("--spacing", type=float, default=TriageConfig.spacing_m)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "triage.json")
    args = ap.parse_args()
    cfg = TriageConfig(spacing_m=args.spacing)
    clips = []
    for pd in args.pass_dirs:
        defects = json.loads((pd / "truth" / "defects.json").read_text())
        for cd in sorted(pd.glob("clip_*")):
            r = run_clip(cd, defects, args.calib, cfg)
            r["pass"] = pd.name
            clips.append(r)
            print(json.dumps(r))
    frames = sum(c["frames"] for c in clips)
    kept = sum(c["kept"] for c in clips)
    dist = sum(c["true_distance_m"] for c in clips)
    est = sum(c["distance_m"] for c in clips)
    cov_all = sum(c["defects_covered_all"] for c in clips)
    cov_kept = sum(c["defects_covered_kept"] for c in clips)
    cov2 = sum(c["defects_covered_kept_2plus"] for c in clips)
    summary = {
        "spacing_m": cfg.spacing_m,
        "clips": len(clips),
        "frames": frames,
        "kept": kept,
        "keep_rate_pct": round(100 * kept / max(frames, 1), 2),
        "kept_per_km": round(1000 * kept / max(dist, 1e-6), 1),
        "true_distance_km": round(dist / 1000, 3),
        "odometry_err_pct": round(100 * (est - dist) / max(dist, 1e-6), 2),
        "defects_covered": cov_all,
        "recall_loss_pct": round(100 * (cov_all - cov_kept) / max(cov_all, 1), 2),
        "covered_2plus_pct": round(100 * cov2 / max(cov_all, 1), 1),
        "ms_per_frame": round(float(np.mean([c["ms_per_frame"] for c in clips])), 1) if clips else None,
    }
    print(json.dumps(summary, indent=1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "clips": clips}, indent=1))


if __name__ == "__main__":
    main()
