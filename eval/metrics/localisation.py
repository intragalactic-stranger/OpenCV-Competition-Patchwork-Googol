"""Localisation accuracy against synthetic truth.

Per frame: estimated position (smoothed chainage on the mapped centreline) vs the TRUE camera position
(chainage + lateral offset), as a planar distance in metres. Also reported:
  - raw GNSS error (the baseline the proposal's "<= 8 m" was set against)
  - error inside tunnels (no GNSS: odometry only)
A defect's position error equals the frame error plus the road-plane offset error (centimetres, see the
area eval), so the frame error is the localisation metric.

Usage: uv run python -m eval.metrics.localisation data/synth/seed07/pass_1 [...]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from patchwork.perception import calib as calib_mod
from patchwork.perception.ipm import camera_from_calibration
from patchwork.perception.localise import TO_UTM, localise
from patchwork.perception.triage import triage_video
from patchwork.synth.corridor import load_corridor
from patchwork.synth.motion import true_positions

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "eval" / "results" / "cache"


def _csv(path: Path) -> dict[str, np.ndarray]:
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) if r[k] != "" else np.nan for r in rows]) for k in rows[0]}


def odometry(clip_dir: Path, cal_path: Path) -> np.ndarray:
    key = CACHE / f"odo_{clip_dir.parent.parent.name}_{clip_dir.parent.name}_{clip_dir.name}.npy"
    if key.exists():
        return np.load(key)
    meta = json.loads((clip_dir / "meta.json").read_text())
    cam = camera_from_calibration(calib_mod.load(cal_path), meta["mount_height_m"], meta["nominal_pitch_deg"])
    res = triage_video(str(clip_dir / "clip.mp4"), cam, meta["fps"])
    odo = np.array([s.travel_m for s in res.scores])
    key.parent.mkdir(parents=True, exist_ok=True)
    np.save(key, odo)
    return odo


def run_clip(c, clip_dir: Path, cal_path: Path) -> dict:
    fr = _csv(clip_dir / "frames.csv")
    g = _csv(clip_dir / "gnss.csv")
    odo = odometry(clip_dir, cal_path)
    n = min(len(odo), len(fr["t"]))
    tr = localise(c, fr["t"][:n], odo[:n], g["t"], g["lat"], g["lon"], g["hdop"])
    tx, ty, _ = true_positions(c, fr["s"][:n], fr["lateral"][:n])
    ex, ey, _ = true_positions(c, tr.s, tr.d)
    err = np.hypot(ex - tx, ey - ty)
    # raw GNSS vs truth at the fix times
    ok = np.isfinite(g["lat"])
    gx, gy = TO_UTM.transform(g["lon"][ok], g["lat"][ok])
    s_at = np.interp(g["t"][ok], fr["t"], fr["s"])
    l_at = np.interp(g["t"][ok], fr["t"], fr["lateral"])
    gtx, gty, _ = true_positions(c, s_at, l_at)
    gerr = np.hypot(np.asarray(gx) - gtx, np.asarray(gy) - gty)
    tunnel = np.array([c.segment_at(float(si)).is_tunnel for si in fr["s"][:n]])
    return {
        "clip": f"{clip_dir.parent.name}/{clip_dir.name}",
        "frames": int(n),
        "median_m": round(float(np.median(err)), 2),
        "p90_m": round(float(np.percentile(err, 90)), 2),
        "max_m": round(float(err.max()), 2),
        "gnss_median_m": round(float(np.median(gerr)), 2) if len(gerr) else None,
        "tunnel_frames": int(tunnel.sum()),
        "tunnel_median_m": round(float(np.median(err[tunnel])), 2) if tunnel.any() else None,
        "within_2sigma": round(float(np.mean(err <= 2 * np.maximum(tr.sigma, 0.5))), 3),
        "_in2s": err <= 2 * np.maximum(tr.sigma, 0.5),
        "odo_scale": round(tr.scale, 4),
        "gnss_used": tr.gnss_used,
        "_err": err,
        "_gerr": gerr,
        "_tunnel": tunnel,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_dirs", nargs="+", type=Path)
    ap.add_argument("--calib", type=Path, default=ROOT / "data" / "calib" / "cam01-v1.json")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "localisation.json")
    args = ap.parse_args()
    c = load_corridor(ROOT / "data" / "corridor")
    clips = []
    for pd in args.pass_dirs:
        for cd in sorted(pd.glob("clip_*")):
            r = run_clip(c, cd, args.calib)
            clips.append(r)
            print(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}), flush=True)
    err = np.concatenate([r["_err"] for r in clips])
    gerr = np.concatenate([r["_gerr"] for r in clips])
    tun = np.concatenate([r["_tunnel"] for r in clips])
    summary = {
        "clips": len(clips),
        "frames": int(len(err)),
        "median_m": round(float(np.median(err)), 2),
        "p90_m": round(float(np.percentile(err, 90)), 2),
        "p99_m": round(float(np.percentile(err, 99)), 2),
        "gnss_only_median_m": round(float(np.median(gerr)), 2),
        "gnss_only_p90_m": round(float(np.percentile(gerr, 90)), 2),
        "within_2sigma": round(float(np.concatenate([r["_in2s"] for r in clips]).mean()), 3),
        "tunnel_frames": int(tun.sum()),
        "tunnel_median_m": round(float(np.median(err[tun])), 2) if tun.any() else None,
        "tunnel_p90_m": round(float(np.percentile(err[tun], 90)), 2) if tun.any() else None,
    }
    print(json.dumps(summary, indent=1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"summary": summary, "clips": [{k: v for k, v in r.items() if not k.startswith("_")} for r in clips]},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
