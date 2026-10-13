"""End-to-end evaluation of the pipeline's defect list against synthetic truth (held-out world).

Matching: each detected defect is matched to the nearest unmatched truth defect in road coordinates
(chainage s, lateral d) within a gate of `--gate` m along-track and 2 m across (localisation error is
mostly along-track, ~4 m median; defects are ~120 m apart on average, so the gate is unambiguous).

  recall (D1)          matched / visible truth defects (state != repaired, within the camera's lateral view)
  false positives / km unmatched detections per km driven; reported for the Coastal Road control section (D2)
                       separately, where the surface is clean by construction
  area MAPE            |measured - true| / true over matched defects that were measured (status measured)
  position error       planar distance estimated vs true centre for matched defects
  patch false alarms   detections that land on a *repaired* patch (a classic false positive)

Usage: uv run python -m eval.metrics.end_to_end data/synth/seed11/pass_1 --runs runs/e2e/seed11
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from patchwork.synth.corridor import load_corridor

ROOT = Path(__file__).resolve().parents[2]


def evaluate(pass_dir: Path, run_root: Path, gate: float = 12.0, lateral_view: float = 4.5) -> dict:
    corridor = load_corridor(ROOT / "data" / "corridor")
    truth = json.loads((pass_dir / "truth" / "defects.json").read_text())
    det, km, km_control, stats = [], 0.0, 0.0, []
    for clip in sorted(pass_dir.glob("clip_*")):
        rd = run_root / pass_dir.name / clip.name
        if not (rd / "defects.json").exists():
            continue
        det += json.loads((rd / "defects.json").read_text())
        st = json.loads((rd / "stats.json").read_text())
        stats.append(st)
        km += st["km"]
        meta = json.loads((clip / "meta.json").read_text())
        a, b = meta["chainage_m"]
        for seg in corridor.segments:
            if seg.is_control:
                km_control += max(0.0, min(b, seg.chainage_end_m) - max(a, seg.chainage_start_m)) / 1000
    covered = [
        (json.loads((c / "meta.json").read_text())["chainage_m"])
        for c in sorted(pass_dir.glob("clip_*"))
        if (run_root / pass_dir.name / c.name / "defects.json").exists()
    ]

    def in_range(s: float) -> bool:
        return any(a + 12 <= s <= b for a, b in covered)  # +12: the first metres are never in the measuring band

    visible = [
        t
        for t in truth
        if t["area_m2"] is not None and abs(t["centroid_d"]) <= lateral_view and in_range(t["centroid_s"])
    ]
    patches = [t for t in truth if t["state"] == "repaired" and in_range(t["centroid_s"])]
    used: set[int] = set()
    matches, fps = [], []
    for d in sorted(det, key=lambda d: -d["confidence"]):
        best, best_dist = None, None
        for i, t in enumerate(visible):
            if i in used:
                continue
            ds, dd = abs(d["s"] - t["centroid_s"]), abs(d["d"] - t["centroid_d"])
            if ds <= gate and dd <= 2.0 and (best_dist is None or ds + dd < best_dist):
                best, best_dist = i, ds + dd
        if best is None:
            fps.append(d)
        else:
            used.add(best)
            matches.append((d, visible[best]))
    on_patch = sum(
        any(abs(f["s"] - p["centroid_s"]) <= gate and abs(f["d"] - p["centroid_d"]) <= 2.0 for p in patches)
        for f in fps
    )
    errs = [100 * (d["area_m2"] - t["area_m2"]) / t["area_m2"] for d, t in matches if d["area_m2"] is not None]
    pos = [float(np.hypot(d["s"] - t["centroid_s"], d["d"] - t["centroid_d"])) for d, t in matches]
    fp_control = [f for f in fps if f["is_control"]]
    by_kind = {}
    for k in sorted({t["kind"] for t in visible}):
        n_k = sum(t["kind"] == k for t in visible)
        by_kind[k] = round(sum(t["kind"] == k for _, t in matches) / max(n_k, 1), 3)
    return {
        "pass": pass_dir.name,
        "clips": len(stats),
        "km": round(km, 2),
        "truth_visible": len(visible),
        "detections": len(det),
        "matched": len(matches),
        "recall": round(len(matches) / max(len(visible), 1), 3),
        "recall_by_kind": by_kind,
        "false_positives": len(fps),
        "fp_per_km": round(len(fps) / max(km, 1e-6), 2),
        "control_km": round(km_control, 2),
        "fp_control": len(fp_control),
        "fp_per_km_control": round(len(fp_control) / km_control, 2) if km_control > 0 else None,
        "fp_on_repaired_patches": int(on_patch),
        "area_measured": len(errs),
        "area_mape_pct": round(float(np.mean(np.abs(errs))), 2) if errs else None,
        "area_median_ape_pct": round(float(np.median(np.abs(errs))), 2) if errs else None,
        "area_bias_pct": round(float(np.mean(errs)), 2) if errs else None,
        "position_median_m": round(float(np.median(pos)), 2) if pos else None,
        "seconds_per_km": round(sum(s["seconds"] for s in stats) / max(km, 1e-6), 1),
        "stage_seconds": {k: round(sum(s["stage_seconds"][k] for s in stats), 1) for k in stats[0]["stage_seconds"]}
        if stats
        else {},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_dirs", nargs="+", type=Path)
    ap.add_argument("--runs", type=Path, required=True, help="runner output root (<runs>/<pass>/<clip>/...)")
    ap.add_argument("--gate", type=float, default=12.0)
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "end_to_end.json")
    args = ap.parse_args()
    res = [evaluate(pd, args.runs, args.gate) for pd in args.pass_dirs]
    for r in res:
        print(json.dumps(r, indent=1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"passes": res}, indent=1))


if __name__ == "__main__":
    main()
