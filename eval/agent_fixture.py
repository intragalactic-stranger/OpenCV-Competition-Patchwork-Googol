"""Load (or remove) a labelled agent-development fixture: ground-truth defects of the held-out world.

  uv run python -m eval.agent_fixture load --pass-dir data/synth/seed11/pass_1 [--n 40]
  uv run python -m eval.agent_fixture remove
Rows use pass_id 'fixture-truth' and model_version 'ground-truth' so they can never be mistaken for pipeline
output, and `remove` deletes exactly them (and any work packages that cite them).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from patchwork.register.dataapi import Register
from patchwork.schema.models import (
    DefectType,
    Material,
    MeasurementStatus,
    Observation,
    new_id,
    severity_v1,
)
from patchwork.synth.corridor import load_corridor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PASS = "fixture-truth"


def load(reg: Register, pass_dir: Path, n: int) -> int:
    corridor = load_corridor(ROOT / "data" / "corridor")
    truth = [t for t in json.loads((pass_dir / "truth" / "defects.json").read_text()) if t["area_m2"]]
    truth.sort(key=lambda t: t["centroid_s"])
    step = max(len(truth) // n, 1)
    k = 0
    for t in truth[::step][:n]:
        seg = corridor.segment_at(t["centroid_s"])
        kind = DefectType(t["kind"])
        sev, sc = severity_v1(
            t["area_m2"],
            kind,
            t["length_m"],
            t["attributes"].get("wheel_path", False),
            t["attributes"].get("water", False),
        )
        o = Observation(
            pass_id=FIXTURE_PASS,
            clip_id="fixture",
            frame_idx=k,
            frame_ts=dt.datetime.now(dt.UTC),
            lat=t["lat"],
            lon=t["lon"],
            gnss_hdop_proxy=0.0,
            road_segment_id=seg.segment_id,
            road_name=seg.name,
            chainage_m=t["centroid_s"],
            lateral_offset_m=t["centroid_d"],
            defect_type=kind,
            area_m2=t["area_m2"],
            area_uncertainty_m2=0.0,
            length_m=t["length_m"],
            width_m=t["width_m"],
            measurement_status=MeasurementStatus.measured,
            severity=sev,
            severity_confidence=sc,
            detection_confidence=1.0,
            material=Material.for_area(t["area_m2"]),
            attributes={
                "source": "fixture (ground truth)",
                "wheel_path": t["attributes"].get("wheel_path", False),
                "water_pooling": t["attributes"].get("water", False),
                "truth_id": t["truth_id"],
            },
            calibration_id="n/a",
            model_version="ground-truth",
            pipeline_version="fixture",
            privacy_blurred=True,
        )
        did = new_id()
        reg.sql(
            "INSERT INTO defect (defect_id, first_seen_pass, last_seen_pass, status, latest_obs_id, lat, lon, "
            "road_segment_id, road_name, chainage_m, latest_area_m2, latest_severity) VALUES (:d, :p, :p, 'new', :o, "
            ":lat, :lon, :seg, :rn, :s, :a, CAST(:sev AS severity))",
            {
                "d": did,
                "p": FIXTURE_PASS,
                "o": o.obs_id,
                "lat": o.lat,
                "lon": o.lon,
                "seg": o.road_segment_id,
                "rn": o.road_name,
                "s": o.chainage_m,
                "a": o.area_m2,
                "sev": o.severity.value,
            },
        )
        row = o.model_dump(mode="json", exclude={"created_at"})
        row["frame_ts"] = o.frame_ts
        row["defect_id"] = did
        casts = {
            "defect_type": "defect_type",
            "measurement_status": "measurement_status",
            "severity": "severity",
            "material": "jsonb",
            "attributes": "jsonb",
        }
        vals = ", ".join(f"CAST(:{c} AS {casts[c]})" if c in casts else f":{c}" for c in row)
        reg.sql(
            f"INSERT INTO observation ({', '.join(row)}) VALUES ({vals})",
            {c: json.dumps(v) if c in ("material", "attributes") else v for c, v in row.items()},
        )
        k += 1
    return k


def remove(reg: Register) -> None:
    for table in ("approval_request", "approval", "ticket", "reinspection"):
        reg.sql(
            f"DELETE FROM {table} WHERE package_id IN (SELECT package_id FROM work_package wp WHERE EXISTS "
            "(SELECT 1 FROM defect d WHERE d.defect_id = ANY(wp.defect_ids) AND d.first_seen_pass = :p))",
            {"p": FIXTURE_PASS},
        )
    reg.sql(
        "DELETE FROM work_package wp WHERE EXISTS (SELECT 1 FROM defect d WHERE d.defect_id = ANY(wp.defect_ids) "
        "AND d.first_seen_pass = :p)",
        {"p": FIXTURE_PASS},
    )
    reg.sql("UPDATE observation SET defect_id = NULL WHERE pass_id = :p", {"p": FIXTURE_PASS})
    reg.sql("DELETE FROM defect WHERE first_seen_pass = :p", {"p": FIXTURE_PASS})
    reg.sql("DELETE FROM observation WHERE pass_id = :p", {"p": FIXTURE_PASS})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["load", "remove"])
    ap.add_argument("--pass-dir", type=Path, default=ROOT / "data" / "synth" / "seed11" / "pass_1")
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    reg = Register()
    if args.cmd == "load":
        print(f"loaded {load(reg, args.pass_dir, args.n)} fixture defects")
    else:
        remove(reg)
        print("fixture removed", reg.sql("SELECT count(*) n FROM defect"))


if __name__ == "__main__":
    main()
