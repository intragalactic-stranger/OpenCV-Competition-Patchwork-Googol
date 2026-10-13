"""Process one clip end to end: video + GNSS -> list of measured, geo-located defects (the register input).

  decode -> [1] triage -> [2] privacy blur -> pitch from lane lines -> [5] segment (OpenCV 5 DNN)
         -> per component: perspective mask -> bird's-eye view -> m² -> [8] localise -> [9] track & fuse

  uv run python -m patchwork.pipeline.runner perceive data/synth/seed11/pass_1/clip_0* --model M --out runs/e2e
  uv run python -m patchwork.pipeline.runner assemble data/synth/seed11/pass_1 --model M --out runs/e2e --overlays
perceive  (per clip, parallel on Batch): <out>/<pass>/<clip>/perception.json (observations + odometry)
assemble  (per pass, sequential, cheap): localisation with the route-progress hint, tracking, defects.json,
          stats.json, overlays/<defect>.jpg
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from patchwork.perception import calib as calib_mod
from patchwork.perception.ipm import IPM, camera_from_calibration
from patchwork.perception.localise import TO_WGS, Track, localise
from patchwork.perception.measure import FrameMeasurement, fuse, measure_bev, truncated_in_image
from patchwork.perception.pose import PitchEstimator
from patchwork.perception.privacy import Privacy
from patchwork.perception.segment import Segmenter
from patchwork.perception.triage import Triage
from patchwork.synth.corridor import Corridor, load_corridor

ROOT = Path(__file__).resolve().parents[3]
LINK_M = 1.2  # observations closer than this (road coordinates) belong to the same defect


@dataclass
class Observation:
    frame: int
    X: float  # m right of the camera
    Y: float  # m ahead
    area_m2: float
    length_m: float
    width_m: float
    uncertainty_m2: float
    touches_border: bool
    prob: float  # mean damage probability inside the component
    near_blur: bool  # overlaps a privacy-blurred region
    s: float = 0.0  # road chainage (filled after localisation)
    d: float = 0.0  # lateral offset (filled after localisation)


@dataclass
class DefectTrack:
    defect_id: str
    s: float
    d: float
    lat: float
    lon: float
    position_sigma_m: float
    area_m2: float | None  # None = detected but never fully inside the measurement band
    uncertainty_m2: float | None
    length_m: float | None
    width_m: float | None
    confidence: float
    n_observations: int
    best_frame: int
    road_name: str
    segment_id: str
    is_control: bool
    measurement_status: str
    frames: list[int] = field(default_factory=list)


def _csv(path: Path) -> dict[str, np.ndarray]:
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) if r[k] != "" else np.nan for r in rows]) for k in rows[0]}


def _link(obs: list[Observation]) -> list[list[Observation]]:
    """Greedy single-pass clustering along the road (observations sorted by chainage)."""
    groups: list[list[Observation]] = []
    for o in sorted(obs, key=lambda o: o.s):
        for g in reversed(groups[-6:]):
            cs, cd = np.median([x.s for x in g]), np.median([x.d for x in g])
            if abs(o.s - cs) < LINK_M and abs(o.d - cd) < LINK_M:
                g.append(o)
                break
        else:
            groups.append([o])
    return groups


def assemble(
    corridor: Corridor,
    clip_dir: Path,
    obs: list[Observation],
    odo: np.ndarray,
    stats: dict,
    s_hint: float | None = None,
    min_obs: int = 2,
    min_prob: float = 0.6,
) -> tuple[list[DefectTrack], dict]:
    """The cheap, sequential part: localise the clip (route-progress hint), place, link and fuse observations."""
    meta = json.loads((clip_dir / "meta.json").read_text())
    fr = _csv(clip_dir / "frames.csv")  # only the timestamps are used (not the truth columns)
    g = _csv(clip_dir / "gnss.csv")
    n = min(len(odo), len(fr["t"]))
    track: Track = localise(corridor, fr["t"][:n], odo[:n], g["t"], g["lat"], g["lon"], g["hdop"], s_hint=s_hint)
    for o in obs:
        o.s, o.d = float(track.s[o.frame] + o.Y), float(track.d[o.frame] + o.X)
    defects = []
    for gi, grp in enumerate(_link(obs)):
        prob = float(np.mean([o.prob for o in grp]))
        if len(grp) < min_obs or prob < min_prob:
            continue
        fm = fuse(
            [
                FrameMeasurement(o.area_m2, o.length_m, o.width_m, o.X, o.Y, o.uncertainty_m2, o.touches_border)
                for o in grp
            ]
        )
        best = min(grp, key=lambda o: abs(o.Y - 8.0))
        s_c, d_c = float(np.median([o.s for o in grp])), float(np.median([o.d for o in grp]))
        x, y, h = corridor.pose_at(s_c)
        lon, lat = TO_WGS.transform(x + d_c * np.sin(h), y - d_c * np.cos(h))
        segm = corridor.segment_at(s_c)
        defects.append(
            DefectTrack(
                defect_id=f"{meta['clip_id']}-d{gi:04d}",
                s=round(s_c, 2),
                d=round(d_c, 2),
                lat=float(lat),
                lon=float(lon),
                position_sigma_m=round(float(track.sigma[best.frame]), 2),
                area_m2=None if fm is None else round(fm.area_m2, 4),
                uncertainty_m2=None if fm is None else round(fm.uncertainty_m2, 4),
                length_m=None if fm is None else round(fm.length_m, 3),
                width_m=None if fm is None else round(fm.width_m, 3),
                confidence=round(prob * min(1.0, len(grp) / 4), 3),
                n_observations=len(grp),
                best_frame=best.frame,
                road_name=segm.name,
                segment_id=segm.segment_id,
                is_control=segm.is_control,
                measurement_status="measured" if fm is not None else "detected_not_measured",
                frames=sorted({o.frame for o in grp}),
            )
        )
    stats = {
        **stats,
        "defects": len(defects),
        "s_start": round(float(track.s[0]), 1),
        "s_end": round(float(track.s[-1]), 1),
    }
    return defects, stats


class ClipRunner:
    def __init__(self, model: Path, calib: Path, corridor: Corridor, min_obs: int = 2, min_prob: float = 0.6):
        self.cal = calib_mod.load(calib)
        self.corridor = corridor
        self.seg = Segmenter(model)
        self.privacy = Privacy()
        self.min_obs, self.min_prob = min_obs, min_prob

    def run(self, clip_dir: Path, s_hint: float | None = None) -> tuple[list[DefectTrack], list[Observation], dict]:
        """perceive + assemble for one clip (local runs)."""
        obs, odo, st = self.perceive(clip_dir)
        defects, st = assemble(self.corridor, clip_dir, obs, odo, st, s_hint, self.min_obs, self.min_prob)
        return defects, obs, st

    def perceive(self, clip_dir: Path) -> tuple[list[Observation], np.ndarray, dict]:
        """The heavy, parallel part: decode -> triage -> blur -> pitch -> segment -> per-component m²."""
        t0 = time.time()
        meta = json.loads((clip_dir / "meta.json").read_text())
        cam = camera_from_calibration(self.cal, meta["mount_height_m"], meta["nominal_pitch_deg"])
        triage = Triage(cam, meta["fps"])
        pitch = PitchEstimator(cam)
        base = IPM(cam)
        ipms: dict[float, IPM] = {}
        obs: list[Observation] = []
        cap = cv2.VideoCapture(str(clip_dir / "clip.mp4"))
        stage = {"decode_triage": 0.0, "privacy": 0.0, "pose": 0.0, "segment": 0.0, "measure": 0.0}
        idx = 0
        while True:
            ta = time.time()
            ok, frame = cap.read()
            if not ok:
                break
            score = triage.push(frame)
            stage["decode_triage"] += time.time() - ta
            if not score.kept:
                idx += 1
                continue
            tb = time.time()
            blurred = self.privacy.apply(frame)
            tc = time.time()
            est = pitch.estimate(blurred.image)
            p = round(est.pitch_deg if est.used else cam.pitch_deg, 2)
            ipm = ipms.get(p) or ipms.setdefault(p, base.with_pose(p))
            td = time.time()
            seg = self.seg.predict(blurred.image)
            te = time.time()
            n, lab, stats, _ = cv2.connectedComponentsWithStats(seg.mask.astype(np.uint8), connectivity=8)
            for k in range(1, n):
                comp = lab == k
                box = tuple(int(v) for v in stats[k, :4])
                m = measure_bev(ipm.warp_mask_box(comp, box), ipm, truncated=truncated_in_image(comp))
                if m is None:
                    continue
                x, y, w, h = stats[k, :4]
                obs.append(
                    Observation(
                        idx,
                        m.centroid_x,
                        m.centroid_y,
                        m.area_m2,
                        m.length_m,
                        m.width_m,
                        m.uncertainty_m2,
                        m.touches_border,
                        float(seg.prob[comp].mean()),
                        blurred.overlaps((x, y, w, h)),
                    )
                )
            stage.update(
                privacy=stage["privacy"] + tc - tb,
                pose=stage["pose"] + td - tc,
                segment=stage["segment"] + te - td,
                measure=stage["measure"] + time.time() - te,
            )
            idx += 1
        cap.release()

        odo = np.array([sc.travel_m for sc in triage.result.scores])
        stats_out = {
            "clip_id": meta["clip_id"],
            "frames": int(len(triage.result.scores)),
            "kept": len(triage.result.kept),
            "km": round(float(odo.sum()) / 1000, 3),
            "observations": len(obs),
            "engine": self.seg.engine,
            "seconds": round(time.time() - t0, 1),
            "stage_seconds": {k: round(v, 1) for k, v in stage.items()},
        }
        return obs, odo, stats_out

    def overlays(self, clip_dir: Path, defects: list[DefectTrack], obs: list[Observation], out_dir: Path) -> int:
        """Evidence image per defect: dashcam crop with the detected outline | metric top-down crop with m²."""
        if not defects:
            return 0
        out_dir.mkdir(parents=True, exist_ok=True)
        meta = json.loads((clip_dir / "meta.json").read_text())
        cam = camera_from_calibration(self.cal, meta["mount_height_m"], meta["nominal_pitch_deg"])
        pitch, base = PitchEstimator(cam), IPM(cam)
        cap = cv2.VideoCapture(str(clip_dir / "clip.mp4"))
        n = 0
        for d in defects:
            cap.set(cv2.CAP_PROP_POS_FRAMES, d.best_frame)
            ok, frame = cap.read()
            if not ok:
                continue
            img = self.privacy.apply(frame).image
            est = pitch.estimate(img)
            ipm = base.with_pose(round(est.pitch_deg if est.used else cam.pitch_deg, 2))
            mask = self.seg.predict(img).mask
            o = min(
                (o for o in obs if o.frame == d.best_frame), key=lambda o: abs(o.s - d.s) + abs(o.d - d.d), default=None
            )
            if o is None:
                continue
            # perspective: crop around the component nearest the defect's ground position
            u, v = cam.ground_to_pixel(np.array([[o.X, o.Y]]), distort=True)[0]
            half = int(np.clip(2600 / max(o.Y, 3.0), 90, 420))
            x0, y0 = int(max(u - 1.6 * half, 0)), int(max(v - half, 0))
            x1, y1 = int(min(u + 1.6 * half, img.shape[1])), int(min(v + half, img.shape[0]))
            persp = img.copy()
            cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(persp, cnts, -1, (0, 0, 255), 3)
            left = cv2.resize(persp[y0:y1, x0:x1], None, fx=300 / max(y1 - y0, 1), fy=300 / max(y1 - y0, 1))
            # top-down: 3 m x 3 m around the defect at 1 cm/px, 0.5 m grid
            bev = ipm.warp(img)
            bm = ipm.warp_mask(mask)
            cx, cy = ipm.spec.pixel_of(np.array(o.X), np.array(o.Y))
            r = 150
            bx0, by0 = int(np.clip(cx - r, 0, bev.shape[1] - 2 * r)), int(np.clip(cy - r, 0, bev.shape[0] - 2 * r))
            crop = bev[by0 : by0 + 2 * r, bx0 : bx0 + 2 * r].copy()
            mc = bm[by0 : by0 + 2 * r, bx0 : bx0 + 2 * r].astype(np.uint8)
            for g in range(0, 2 * r, 50):
                cv2.line(crop, (g, 0), (g, 2 * r), (255, 255, 255), 1)
                cv2.line(crop, (0, g), (2 * r, g), (255, 255, 255), 1)
            cnts, _ = cv2.findContours(mc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(crop, cnts, -1, (0, 0, 255), 2)
            label = f"{d.area_m2:.2f} m2" if d.area_m2 is not None else "not measured"
            cv2.putText(crop, label, (8, 2 * r - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(crop, label, (8, 2 * r - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(crop, "grid 0.5 m", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            right = cv2.resize(crop, (300, 300))
            cv2.imwrite(str(out_dir / f"{d.defect_id}.jpg"), np.hstack([left, right]), [cv2.IMWRITE_JPEG_QUALITY, 85])
            n += 1
        cap.release()
        return n


def save_perception(out: Path, obs: list[Observation], odo: np.ndarray, st: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "perception.json").write_text(
        json.dumps(
            {"stats": st, "odometry_m": [round(float(v), 4) for v in odo], "observations": [asdict(o) for o in obs]}
        )
    )


def load_perception(out: Path) -> tuple[list[Observation], np.ndarray, dict]:
    d = json.loads((out / "perception.json").read_text())
    return [Observation(**o) for o in d["observations"]], np.array(d["odometry_m"]), d["stats"]


def assemble_pass(corridor: Corridor, pass_dir: Path, run_pass: Path, runner: ClipRunner | None = None) -> list[dict]:
    """Sequential over a pass: each clip's localisation continues where the previous clip ended."""
    hint, out = 0.0, []
    for clip in sorted(pass_dir.glob("clip_*")):
        rd = run_pass / clip.name
        if not (rd / "perception.json").exists():
            hint = None  # a missing clip breaks the chain; fall back to geometry-only anchoring
            continue
        obs, odo, st = load_perception(rd)
        defects, st = assemble(corridor, clip, obs, odo, st, hint)
        hint = st["s_end"]
        (rd / "defects.json").write_text(json.dumps([asdict(d) for d in defects], indent=1))
        if runner is not None:
            st["overlays"] = runner.overlays(clip, defects, obs, rd / "overlays")
        (rd / "stats.json").write_text(json.dumps(st, indent=1))
        out.append(st)
        print(json.dumps(st), flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("perceive", help="heavy per-clip stage (parallel)")
    pc.add_argument("clips", nargs="+", type=Path)
    asm = sub.add_parser("assemble", help="per-pass stage: localise, track, fuse (+ overlays)")
    asm.add_argument("pass_dir", type=Path)
    for p in (pc, asm):
        p.add_argument("--model", type=Path, required=True)
        p.add_argument("--calib", type=Path, default=ROOT / "data" / "calib" / "cam01-v1.json")
        p.add_argument("--out", type=Path, required=True, help="run root: <out>/<pass>/<clip>/")
    asm.add_argument("--overlays", action="store_true", help="also write one evidence image per defect")
    args = ap.parse_args()
    corridor = load_corridor(ROOT / "data" / "corridor")
    if args.cmd == "perceive":
        runner = ClipRunner(args.model, args.calib, corridor)
        for clip in sorted(args.clips):
            obs, odo, st = runner.perceive(clip)
            save_perception(args.out / clip.parent.name / clip.name, obs, odo, st)
            print(json.dumps(st), flush=True)
    else:
        runner = ClipRunner(args.model, args.calib, corridor) if args.overlays else None
        assemble_pass(corridor, args.pass_dir, args.out / args.pass_dir.name, runner)


if __name__ == "__main__":
    main()
