"""Defect register on Aurora PostgreSQL (PostGIS) through the RDS Data API.

  uv run python -m patchwork.register.dataapi migrate          # apply schema/ddl.sql (idempotent)
  uv run python -m patchwork.register.dataapi load-corridor    # road segments + POIs
  uv run python -m patchwork.register.dataapi load-run RUN_DIR --pass-dir data/synth/seed11/pass_1 --model seg-v1
  uv run python -m patchwork.register.dataapi summary

Cluster/secret ARNs come from Terraform outputs (env PATCHWORK_DB_CLUSTER_ARN / PATCHWORK_DB_SECRET_ARN, or
looked up by name). Loading is idempotent: re-loading a clip (Spot retry, re-upload) adds nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from patchwork.schema.models import (
    DefectType,
    Material,
    MeasurementStatus,
    Observation,
    new_id,
    severity_v1,
)

ROOT = Path(__file__).resolve().parents[3]
REGION = "ap-south-1"
DDL = ROOT / "src" / "patchwork" / "schema" / "ddl.sql"
PIPELINE_VERSION = "0.2"
LINK_M = 8.0  # cross-pass: same defect if within this distance on the same road (localisation p90 ~6.5 m)
# Links are only made to defects last seen on an EARLIER pass: two tracks of one pass are separate defects
# (perception already fused each defect's frames), so within-pass neighbours never get unchanged/degraded.


def _param(name: str, v) -> dict:
    if v is None:
        return {"name": name, "value": {"isNull": True}}
    if isinstance(v, bool):
        return {"name": name, "value": {"booleanValue": v}}
    if isinstance(v, int):
        return {"name": name, "value": {"longValue": v}}
    if isinstance(v, float):
        return {"name": name, "value": {"doubleValue": v}}
    if isinstance(v, dt.datetime):
        return {"name": name, "value": {"stringValue": v.strftime("%Y-%m-%d %H:%M:%S")}, "typeHint": "TIMESTAMP"}
    if isinstance(v, dict | list):
        return {"name": name, "value": {"stringValue": json.dumps(v)}, "typeHint": "JSON"}
    return {"name": name, "value": {"stringValue": str(v)}}


def split_sql(text: str) -> list[str]:
    """Split a SQL script on ';' outside $$-quoted bodies and comments."""
    text = re.sub(r"--[^\n]*", "", text)
    out, buf, in_dollar = [], [], False
    for part in re.split(r"(\$\$|;)", text):
        if part == "$$":
            in_dollar = not in_dollar
            buf.append(part)
        elif part == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(part)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


class Register:
    def __init__(self, cluster_arn: str | None = None, secret_arn: str | None = None, database: str = "patchwork"):
        self.rds = boto3.client("rds-data", region_name=REGION)
        cluster_arn = cluster_arn or os.environ.get("PATCHWORK_DB_CLUSTER_ARN")
        secret_arn = secret_arn or os.environ.get("PATCHWORK_DB_SECRET_ARN")
        if not cluster_arn or not secret_arn:  # dev box: look them up (Batch jobs get them via env)
            c = boto3.client("rds", region_name=REGION).describe_db_clusters(DBClusterIdentifier="patchwork-register")[
                "DBClusters"
            ][0]
            cluster_arn, secret_arn = c["DBClusterArn"], c["MasterUserSecret"]["SecretArn"]
        self.cluster_arn, self.secret_arn, self.database = cluster_arn, secret_arn, database

    def sql(self, statement: str, params: dict | None = None) -> list[dict]:
        kw = dict(
            resourceArn=self.cluster_arn,
            secretArn=self.secret_arn,
            database=self.database,
            sql=statement,
            parameters=[_param(k, v) for k, v in (params or {}).items()],
            formatRecordsAs="JSON",
        )
        for attempt in range(12):  # an auto-paused cluster takes ~15-30 s to resume
            try:
                r = self.rds.execute_statement(**kw)
                return json.loads(r["formattedRecords"]) if r.get("formattedRecords") else []
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("DatabaseResumingException", "DatabaseNotFoundException") or "resum" in str(e).lower():
                    time.sleep(min(5 * (attempt + 1), 20))
                    continue
                raise
        raise TimeoutError("database did not resume")

    # ------------------------------------------------------------------ schema + reference data
    def migrate(self) -> int:
        stmts = split_sql(DDL.read_text())
        for s in stmts:
            self.sql(s)
        return len(stmts)

    def load_corridor(self, corridor_dir: Path = ROOT / "data" / "corridor") -> tuple[int, int]:
        segs = json.loads((corridor_dir / "segments.geojson").read_text())["features"]
        for f in segs:
            p = f["properties"]
            self.sql(
                "INSERT INTO road_segment VALUES (:id, :name, :hw, :ctl, :tun, :s0, :s1, "
                "ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) ON CONFLICT (road_segment_id) DO NOTHING",
                {
                    "id": p["segment_id"],
                    "name": p["name"],
                    "hw": p["highway"],
                    "ctl": p["is_control"],
                    "tun": p["is_tunnel"],
                    "s0": float(p["chainage_start_m"]),
                    "s1": float(p["chainage_end_m"]),
                    "g": json.dumps(f["geometry"]),
                },
            )
        pois = json.loads((corridor_dir / "poi.geojson").read_text())["features"]
        for f in pois:
            p = f["properties"]
            self.sql(
                "INSERT INTO poi VALUES (:id, :kind, :name, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) "
                "ON CONFLICT (poi_id) DO NOTHING",
                {"id": p["poi_id"], "kind": p["kind"], "name": p.get("name"), "g": json.dumps(f["geometry"])},
            )
        return len(segs), len(pois)

    # ------------------------------------------------------------------ pipeline output
    def load_clip(self, run_dir: Path, meta: dict, model_version: str, calibration_id: str) -> dict:
        """Load one clip's defect tracks: observation (idempotent) -> link to an existing defect or create one."""
        tracks = json.loads((run_dir / "defects.json").read_text())
        t0 = dt.datetime.fromisoformat(meta["start_time_utc"].replace("Z", "+00:00"))
        new_obs = new_def = linked = 0
        for t in tracks:
            kind = DefectType.edge_break if abs(t["d"]) > 1.0 and t["d"] < -1.0 else DefectType.pothole
            sev, sev_conf = severity_v1(t["area_m2"], kind, t["length_m"])
            obs = Observation(
                pass_id=meta["pass_id"],
                clip_id=meta["clip_id"],
                frame_idx=t["best_frame"],
                frame_ts=t0 + dt.timedelta(seconds=t["best_frame"] / meta["fps"]),
                lat=t["lat"],
                lon=t["lon"],
                gnss_hdop_proxy=t["position_sigma_m"],
                road_segment_id=t["segment_id"],
                road_name=t["road_name"],
                chainage_m=t["s"],
                lateral_offset_m=t["d"],
                defect_type=kind,
                area_m2=t["area_m2"],
                area_uncertainty_m2=t["uncertainty_m2"],
                length_m=t["length_m"],
                width_m=t["width_m"],
                measurement_status=MeasurementStatus(t["measurement_status"]),
                severity=sev,
                severity_confidence=sev_conf,
                detection_confidence=min(t["confidence"], 1.0),
                material=Material.for_area(t["area_m2"]) if t["area_m2"] is not None else None,
                attributes={"source": "rules", "n_observations": t["n_observations"], "track_id": t["defect_id"]},
                overlay_key=t["defect_id"],  # evidence image name; the viewer deploy maps it to a URL
                calibration_id=calibration_id,
                model_version=model_version,
                pipeline_version=PIPELINE_VERSION,
                privacy_blurred=bool(meta.get("privacy_blurred", True)),
            )
            row = obs.model_dump(mode="json", exclude={"created_at"})
            row["frame_ts"] = obs.frame_ts
            casts = {
                "defect_type": "defect_type",
                "measurement_status": "measurement_status",
                "severity": "severity",
                "material": "jsonb",
                "attributes": "jsonb",
            }
            cols = list(row)
            values = ", ".join(f"CAST(:{c} AS {casts[c]})" if c in casts else f":{c}" for c in cols)
            ins = self.sql(
                f"INSERT INTO observation ({', '.join(cols)}) VALUES ({values}) "
                "ON CONFLICT (clip_id, frame_idx, (round(chainage_m::numeric, 1)), defect_type) DO NOTHING "
                "RETURNING obs_id",
                {
                    c: (json.dumps(row[c]) if c in ("material", "attributes") and row[c] is not None else row[c])
                    for c in cols
                },
            )
            if not ins:
                continue  # already loaded (idempotent re-run)
            new_obs += 1
            near = self.sql(
                "SELECT defect_id, latest_area_m2 FROM defect WHERE road_segment_id = :seg AND last_seen_pass <> :p "
                "AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r) "
                "ORDER BY geom::geography <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography LIMIT 1",
                {"seg": obs.road_segment_id, "lon": obs.lon, "lat": obs.lat, "r": LINK_M, "p": obs.pass_id},
            )
            if near and near[0]["defect_id"]:
                did = near[0]["defect_id"]
                prev = near[0].get("latest_area_m2")
                status = "degraded" if prev and obs.area_m2 and obs.area_m2 > 1.25 * prev else "unchanged"
                self.sql(
                    "UPDATE defect SET last_seen_pass = :p, status = CAST(:st AS defect_status), latest_obs_id = :o, "
                    "latest_area_m2 = COALESCE(:a, latest_area_m2), latest_severity = CAST(:sev AS severity) "
                    "WHERE defect_id = :d",
                    {
                        "p": obs.pass_id,
                        "st": status,
                        "o": obs.obs_id,
                        "a": obs.area_m2,
                        "sev": obs.severity.value,
                        "d": did,
                    },
                )
                self.sql(
                    "INSERT INTO status_event (defect_id, pass_id, from_status, to_status, evidence) VALUES "
                    "(:d, :p, NULL, CAST(:st AS defect_status), CAST(:ev AS jsonb))",
                    {
                        "d": did,
                        "p": obs.pass_id,
                        "st": status,
                        "ev": json.dumps({"prev_area_m2": prev, "area_m2": obs.area_m2, "method": "gnss+chainage"}),
                    },
                )
                linked += 1
            else:
                did = new_id()
                self.sql(
                    "INSERT INTO defect (defect_id, first_seen_pass, last_seen_pass, status, latest_obs_id, lat, lon, "
                    "road_segment_id, road_name, chainage_m, latest_area_m2, latest_severity) VALUES "
                    "(:d, :p, :p, 'new', :o, :lat, :lon, :seg, :rn, :s, :a, CAST(:sev AS severity))",
                    {
                        "d": did,
                        "p": obs.pass_id,
                        "o": obs.obs_id,
                        "lat": obs.lat,
                        "lon": obs.lon,
                        "seg": obs.road_segment_id,
                        "rn": obs.road_name,
                        "s": obs.chainage_m,
                        "a": obs.area_m2,
                        "sev": obs.severity.value,
                    },
                )
                new_def += 1
            self.sql("UPDATE observation SET defect_id = :d WHERE obs_id = :o", {"d": did, "o": obs.obs_id})
        return {
            "clip": meta["clip_id"],
            "tracks": len(tracks),
            "new_observations": new_obs,
            "new_defects": new_def,
            "linked_to_existing": linked,
        }

    def geojson(self) -> dict:
        rows = self.sql(
            "SELECT d.defect_id, d.status, d.road_name, d.chainage_m, d.latest_area_m2, d.latest_severity, "
            "d.lat, d.lon, d.first_seen_pass, d.last_seen_pass, o.area_uncertainty_m2, o.material, "
            "o.detection_confidence, o.measurement_status, o.overlay_key, o.model_version, o.calibration_id "
            "FROM defect d JOIN observation o ON o.obs_id = d.latest_obs_id"
        )
        feats = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r.pop("lon"), r.pop("lat")]},
                "properties": {**r, "material": json.loads(r["material"]) if r.get("material") else None},
            }
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": feats}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("load-corridor")
    lr = sub.add_parser("load-run")
    lr.add_argument("run_dir", type=Path, help="<runs>/<pass> directory with clip_*/defects.json")
    lr.add_argument("--pass-dir", type=Path, required=True, help="the clip directories (for meta.json)")
    lr.add_argument("--model", default="seg-v1")
    lr.add_argument("--calibration", default="cam01-v1")
    sub.add_parser("summary")
    gj = sub.add_parser("geojson")
    gj.add_argument("out", type=Path)
    args = ap.parse_args()
    reg = Register(os.environ.get("PATCHWORK_DB_CLUSTER_ARN"), os.environ.get("PATCHWORK_DB_SECRET_ARN"))
    if args.cmd == "migrate":
        print(f"applied {reg.migrate()} statements")
    elif args.cmd == "load-corridor":
        print("segments, pois:", reg.load_corridor())
    elif args.cmd == "load-run":
        for rd in sorted(args.run_dir.glob("clip_*")):
            meta = json.loads((args.pass_dir / rd.name / "meta.json").read_text())
            print(json.dumps(reg.load_clip(rd, meta, args.model, args.calibration)), flush=True)
    elif args.cmd == "summary":
        for q in (
            "SELECT count(*) AS n FROM road_segment",
            "SELECT count(*) AS n FROM poi",
            "SELECT status, count(*) AS n FROM defect GROUP BY status",
            "SELECT count(*) AS n FROM observation",
        ):
            print(q, "->", reg.sql(q))
    elif args.cmd == "geojson":
        args.out.write_text(json.dumps(reg.geojson()))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
