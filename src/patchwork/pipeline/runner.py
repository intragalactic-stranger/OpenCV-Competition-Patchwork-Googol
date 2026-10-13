"""Process one clip end to end: video + GNSS -> list of measured, geo-located defects (the register input).

  decode -> [1] triage -> [2] privacy blur -> pitch from lane lines -> [5] segment (OpenCV 5 DNN)
         -> per component: perspective mask -> bird's-eye view -> m² -> [8] localise -> [9] track & fuse

  uv run python -m patchwork.pipeline.runner data/synth/seed11/pass_1/clip_03 --model runs/seg-v1/model.onnx
Writes <out>/observations.json (every per-frame measurement) and <out>/defects.json (one row per defect).
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


class ClipRunner:
    def __init__(self, model: Path, calib: Path, corridor: Corridor, min_obs: int = 2, min_prob: float = 0.6):
        self.cal = calib_mod.load(calib)
        self.corridor = corridor
        self.seg = Segmenter(model)
        self.privacy = Privacy()
        self.min_obs, self.min_prob = min_obs, min_prob

    def run(self, clip_dir: Path, s_hint: float | None = None) -> tuple[list[DefectTrack], list[Observation], dict]:
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
                m = measure_bev(ipm.warp_mask(comp), ipm, truncated=truncated_in_image(comp))
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

        fr = _csv(clip_dir / "frames.csv")  # only the timestamps are used (not the truth columns)
        g = _csv(clip_dir / "gnss.csv")
        odo = np.array([s.travel_m for s in triage.result.scores])
        n = min(len(odo), len(fr["t"]))
        track: Track = localise(
            self.corridor, fr["t"][:n], odo[:n], g["t"], g["lat"], g["lon"], g["hdop"], s_hint=s_hint
        )
        for o in obs:
            o.s, o.d = float(track.s[o.frame] + o.Y), float(track.d[o.frame] + o.X)
        defects = []
        for gi, grp in enumerate(_link(obs)):
            prob = float(np.mean([o.prob for o in grp]))
            if len(grp) < self.min_obs or prob < self.min_prob:
                continue
            fm = fuse(
                [
                    FrameMeasurement(o.area_m2, o.length_m, o.width_m, o.X, o.Y, o.uncertainty_m2, o.touches_border)
                    for o in grp
                ]
            )
            best = min(grp, key=lambda o: abs(o.Y - 8.0))
            s_c, d_c = float(np.median([o.s for o in grp])), float(np.median([o.d for o in grp]))
            x, y, h = self.corridor.pose_at(s_c)
            lon, lat = TO_WGS.transform(x + d_c * np.sin(h), y - d_c * np.cos(h))
            segm = self.corridor.segment_at(s_c)
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
        km = float(odo.sum()) / 1000
        stats_out = {
            "clip_id": meta["clip_id"],
            "frames": int(len(triage.result.scores)),
            "kept": len(triage.result.kept),
            "km": round(km, 3),
            "observations": len(obs),
            "defects": len(defects),
            "engine": self.seg.engine,
            "seconds": round(time.time() - t0, 1),
            "stage_seconds": {k: round(v, 1) for k, v in stage.items()},
            "s_start": round(float(track.s[0]), 1),
            "s_end": round(float(track.s[-1]), 1),
        }
        return defects, obs, stats_out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+", type=Path, help="clip dirs; clips of one pass are processed in order")
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--calib", type=Path, default=ROOT / "data" / "calib" / "cam01-v1.json")
    ap.add_argument("--out", type=Path, default=None, help="default: <clip>/run")
    args = ap.parse_args()
    runner = ClipRunner(args.model, args.calib, load_corridor(ROOT / "data" / "corridor"))
    hints: dict[Path, float] = {}  # clips of one pass run in order: each continues where the last ended
    for clip in sorted(args.clips):
        first = clip.name.endswith("_00")
        defects, obs, st = runner.run(clip, 0.0 if first else hints.get(clip.parent))
        hints[clip.parent] = st["s_end"]
        out = args.out / clip.parent.name / clip.name if args.out else clip / "run"
        out.mkdir(parents=True, exist_ok=True)
        (out / "defects.json").write_text(json.dumps([asdict(d) for d in defects], indent=1))
        (out / "observations.json").write_text(json.dumps([asdict(o) for o in obs]))
        (out / "stats.json").write_text(json.dumps(st, indent=1))
        print(json.dumps(st), flush=True)


if __name__ == "__main__":
    main()
