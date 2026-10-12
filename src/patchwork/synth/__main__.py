"""Generate synthetic survey passes over the real Mumbai corridor.

  uv run python -m patchwork.synth --seed 7 --passes 1,2,3                 # full corridor, 3 passes
  uv run python -m patchwork.synth --seed 7 --passes 1 --segment "Khan Abdul Gaffar Khan Marg" --max-m 2000
  uv run python -m patchwork.synth --seed 7 --passes 1 --s-start 1400 --s-end 2400

Layout (per pass)
  <out>/<seed>/pass_<k>/clip_<n>/clip.mp4, frames.csv, gnss.csv, imu.csv, meta.json
  <out>/<seed>/pass_<k>/truth/defects.json, events.json, masks/<clip>_<frame>.png (uint16 instance)
  <out>/<seed>/calib/charuco_<cam>/view_*.png            (input for calibration)
  <out>/<seed>/truth/camera.json                           (true intrinsics; for evaluation only)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from patchwork.camera import CameraModel
from patchwork.synth import charuco
from patchwork.synth.corridor import load_corridor
from patchwork.synth.motion import gnss, imu, road_to_wgs, simulate
from patchwork.synth.render import FramePose, FrameRenderer
from patchwork.synth.world import Defect, World, build_world

ROOT = Path(__file__).resolve().parents[3]


def defect_truth(world: World, k: int, prev: int | None) -> tuple[list[dict], list[dict]]:
    c = world.corridor
    rows, events = [], []
    for i, d in enumerate(world.defects):
        state = d.states[k]
        if state == "absent":
            continue
        poly = d.poly_at(k)
        s_c, d_c = float(poly[:, 0].mean()), float(poly[:, 1].mean())
        lat, lon = road_to_wgs(c, s_c, d_c)
        seg = c.segment_at(s_c)
        rows.append(
            {
                "index": i,
                "truth_id": d.truth_id,
                "kind": d.kind,
                "state": state,
                "area_m2": round(Defect.area(poly), 5) if state != "repaired" else None,
                "area_m2_original": round(Defect.area(d.poly), 5),
                "centroid_s": round(s_c, 3),
                "centroid_d": round(d_c, 3),
                "lat": lat,
                "lon": lon,
                "road_name": seg.name,
                "segment_id": seg.segment_id,
                "is_control": seg.is_control,
                "length_m": round(float(np.ptp(poly[:, 0])), 3),
                "width_m": round(float(np.ptp(poly[:, 1])), 3),
                "attributes": d.attrs,
                "born_pass": d.born_pass,
                "polygon_sd": np.round(poly, 4).tolist(),
            }
        )
        if prev is not None:
            before = d.states[prev]
            event = (
                "new"
                if before == "absent"
                else "repaired"
                if state == "repaired" and before != "repaired"
                else "degraded"
                if state == "degraded"
                else "unchanged"
            )
            events.append({"truth_id": d.truth_id, "from": before, "to": state, "event": event})
    return rows, events


def write_csv(path: Path, cols: dict[str, np.ndarray], fmt: str = "%.6f") -> None:
    keys = list(cols)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        for row in zip(*(cols[k] for k in keys), strict=True):
            w.writerow(
                [
                    ("" if isinstance(v, float) and math.isnan(v) else (fmt % v if isinstance(v, float) else v))
                    for v in (x.item() if hasattr(x, "item") else x for x in row)
                ]
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--passes", default="1", help="comma list of passes to render, e.g. 1,2,3")
    ap.add_argument("--n-passes", type=int, default=None, help="lifecycle length (default: max of --passes)")
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--s-start", type=float, default=0.0)
    ap.add_argument("--s-end", type=float, default=None)
    ap.add_argument("--segment", default=None, help="render only the first stretch of this road name")
    ap.add_argument("--max-m", type=float, default=None, help="cap the rendered length")
    ap.add_argument("--clip-m", type=float, default=3000.0, help="split the pass into clips of this length")
    ap.add_argument("--truth-every", type=int, default=5, help="save GT masks every N frames (0 = never)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synth")
    ap.add_argument("--corridor", type=Path, default=ROOT / "data" / "corridor")
    args = ap.parse_args()

    passes = [int(p) for p in args.passes.split(",")]
    corridor = load_corridor(args.corridor)
    world = build_world(corridor, seed=args.seed, n_passes=args.n_passes or max(passes))
    cam = CameraModel()
    s0, s1 = args.s_start, args.s_end if args.s_end is not None else corridor.length_m
    if args.segment:
        segs = [s for s in corridor.segments if s.name == args.segment]
        if not segs:
            raise SystemExit(f"no segment named {args.segment!r}")
        s0, s1 = segs[0].chainage_start_m, segs[0].chainage_end_m
    if args.max_m:
        s1 = min(s1, s0 + args.max_m)

    root = args.out / f"seed{args.seed:02d}"
    (root / "truth").mkdir(parents=True, exist_ok=True)
    cam.save(root / "truth" / "camera.json")
    calib_dir = root / "calib" / f"charuco_{cam.camera_id}"
    if not calib_dir.exists():
        charuco.render_views(cam, calib_dir, seed=args.seed)
    (root / "world.json").write_text(
        json.dumps(
            {
                "seed": args.seed,
                "n_passes": max(passes),
                "corridor_length_m": corridor.length_m,
                "defects": len(world.defects),
                "features": len(world.features),
                "fps": args.fps,
                "rendered_range_m": [s0, s1],
            },
            indent=2,
        )
    )

    for k in passes:
        t_start = time.time()
        pdir = root / f"pass_{k}"
        (pdir / "truth" / "masks").mkdir(parents=True, exist_ok=True)
        rows, events = defect_truth(world, k, k - 1 if k > 1 else None)
        rows = [r for r in rows if s0 - 5 <= r["centroid_s"] <= s1 + 5]
        (pdir / "truth" / "defects.json").write_text(json.dumps(rows, indent=1))
        if events:
            ids = {r["truth_id"] for r in rows}
            (pdir / "truth" / "events.json").write_text(
                json.dumps([e for e in events if e["truth_id"] in ids], indent=1)
            )

        traj = simulate(world, k, fps=args.fps, s_start=s0, s_end=s1)
        renderer = FrameRenderer(world, k, cam)
        bounds = np.arange(s0, s1, args.clip_m).tolist() + [s1]
        n_frames_total = 0
        for ci, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False)):
            idx = np.where((traj.s >= a) & (traj.s < b if ci < len(bounds) - 2 else traj.s <= b))[0]
            if len(idx) == 0:
                continue
            cdir = pdir / f"clip_{ci:02d}"
            cdir.mkdir(parents=True, exist_ok=True)
            vw = cv2.VideoWriter(
                str(cdir / "clip.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (cam.width, cam.height)
            )
            t0 = traj.t[idx[0]]
            for j, fi in enumerate(idx):
                truth = args.truth_every > 0 and j % args.truth_every == 0
                pose = FramePose(
                    float(traj.s[fi]),
                    float(traj.lateral[fi]),
                    float(traj.pitch[fi]),
                    float(traj.roll[fi]),
                    float(traj.yaw[fi]),
                    float(traj.exposure[fi]),
                )
                fr = renderer.render(pose, with_truth=truth)
                vw.write(fr.image)
                if truth and fr.instance.any():
                    cv2.imwrite(str(pdir / "truth" / "masks" / f"clip{ci:02d}_{j:06d}.png"), fr.instance)
            vw.release()
            n_frames_total += len(idx)
            # per-frame truth poses (for evaluation), clip-relative time
            lat, lon = zip(*(road_to_wgs(corridor, float(traj.s[i]), float(traj.lateral[i])) for i in idx), strict=True)
            write_csv(
                cdir / "frames.csv",
                {
                    "frame": np.arange(len(idx)),
                    "t": traj.t[idx] - t0,
                    "s": traj.s[idx],
                    "lateral": traj.lateral[idx],
                    "speed": traj.speed[idx],
                    "pitch_deg": traj.pitch[idx],
                    "roll_deg": traj.roll[idx],
                    "yaw_deg": traj.yaw[idx],
                    "lat": np.array(lat),
                    "lon": np.array(lon),
                },
            )
            sub = type(traj)(
                traj.t[idx] - t0,
                traj.s[idx],
                traj.speed[idx],
                traj.lateral[idx],
                traj.pitch[idx],
                traj.roll[idx],
                traj.yaw[idx],
                traj.exposure[idx],
                traj.fps,
            )
            write_csv(cdir / "gnss.csv", gnss(world, sub, k * 1000 + ci))
            write_csv(cdir / "imu.csv", imu(sub, world, k * 1000 + ci))
            (cdir / "meta.json").write_text(
                json.dumps(
                    {
                        "pass_id": f"seed{args.seed:02d}-pass{k}",
                        "clip_id": f"seed{args.seed:02d}-pass{k}-clip{ci:02d}",
                        "camera_id": cam.camera_id,
                        "fps": args.fps,
                        "frames": int(len(idx)),
                        "width": cam.width,
                        "height": cam.height,
                        "mount_height_m": cam.mount_height_m,
                        "nominal_pitch_deg": cam.pitch_deg,
                        "chainage_m": [float(traj.s[idx[0]]), float(traj.s[idx[-1]])],
                        "start_time_utc": f"2026-10-{11 + k:02d}T02:30:00Z",
                        "source": "synthetic",
                        "privacy_blurred": True,
                    },
                    indent=2,
                )
            )
            print(
                f"pass {k} clip {ci:02d}: {len(idx)} frames, s {traj.s[idx[0]]:.0f}-{traj.s[idx[-1]]:.0f} m", flush=True
            )
        dt = time.time() - t_start
        print(
            f"pass {k}: {n_frames_total} frames, {(s1 - s0) / 1000:.2f} km, {len(rows)} defects in range, "
            f"{dt / 60:.1f} min ({dt / max(n_frames_total, 1) * 1000:.0f} ms/frame)"
        )


if __name__ == "__main__":
    main()
