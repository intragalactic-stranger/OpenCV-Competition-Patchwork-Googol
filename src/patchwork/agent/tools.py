"""Agent tools. Deterministic, auditable functions over the defect register.

The model decides *which* tool to call and explains the plan; every number (area, material, exposure,
priority) is computed here from database rows, never by the model. Every tool that takes defect or
package IDs validates them first and refuses unknown ones (UNGROUNDED_ID): a hallucinated pothole cannot
become a work order. The database trigger on work_package is the second line of defence.

There is deliberately no `file_complaint` tool: filing is a state of the approval workflow (Step Functions),
reached only after a human approves. The model can request approval, never file.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass

import boto3

from patchwork.register.dataapi import Register
from patchwork.schema.models import HOT_MIX_DENSITY_T_M3, WASTAGE_PCT, new_id

REGION = "ap-south-1"
SEVERITY_W = {"low": 1.0, "medium": 2.0, "high": 4.0}
ROAD_W = {"primary": 1.5, "secondary": 1.2, "tertiary": 1.0, "motorway": 0.6, "motorway_link": 0.6}
CONFIDENCE_FLOOR = 0.6
ACTIVE_STATES = ("draft", "awaiting_approval", "approved", "filed")


class ToolError(Exception):
    """Returned to the model as {"error": code, "detail": ...}; never crashes the run."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Tools:
    reg: Register
    run_id: str = "local"
    approval_state_machine: str | None = None
    artifacts_bucket: str | None = None

    # ------------------------------------------------------------------ helpers
    def _validate_defects(self, ids: list[str]) -> list[dict]:
        if not ids:
            raise ToolError("EMPTY", "no defect_ids given")
        rows = self.reg.sql(
            "SELECT d.defect_id, d.road_segment_id, d.road_name, d.chainage_m, d.latest_area_m2, d.latest_severity, "
            "d.status, d.lat, d.lon, o.measurement_status, o.detection_confidence, o.severity_confidence, "
            "o.area_uncertainty_m2, o.attributes, s.hierarchy, s.is_control "
            "FROM defect d JOIN observation o ON o.obs_id = d.latest_obs_id "
            "JOIN road_segment s ON s.road_segment_id = d.road_segment_id "
            "WHERE d.defect_id IN (SELECT unnest(string_to_array(:ids, ',')))",
            {"ids": ",".join(ids)},
        )
        found = {r["defect_id"] for r in rows}
        unknown = [i for i in ids if i not in found]
        if unknown:
            raise ToolError("UNGROUNDED_ID", f"unknown defect_ids: {unknown[:5]}")
        return rows

    def _package(self, package_id: str) -> dict:
        rows = self.reg.sql(
            "SELECT package_id, array_to_string(defect_ids, ',') AS ids, total_area_m2, material, priority, "
            "exposure_score, confidence, state, pdf_key FROM work_package WHERE package_id = :p",
            {"p": package_id},
        )
        if not rows:
            raise ToolError("UNGROUNDED_ID", f"unknown package_id: {package_id}")
        p = rows[0]
        p["defect_ids"] = p.pop("ids").split(",")
        return p

    # ------------------------------------------------------------------ tools
    def query_defects(
        self,
        road_name: str | None = None,
        min_area_m2: float = 0.0,
        status: str | None = None,
        limit: int = 50,
        defect_ids: list[str] | None = None,
    ) -> list[dict]:
        """Defects in the register, largest first. Filters: road name (substring), minimum area, status, IDs."""
        if defect_ids:
            self._validate_defects(defect_ids)  # asking for an ID that does not exist is an error, not "no rows"
        rows = self.reg.sql(
            "SELECT d.defect_id, d.road_name, round(d.chainage_m::numeric, 1)::float8 AS chainage_m, d.latest_area_m2, "
            "d.latest_severity, d.status, o.measurement_status, o.detection_confidence, o.area_uncertainty_m2 "
            "FROM defect d JOIN observation o ON o.obs_id = d.latest_obs_id "
            "WHERE (:road = '' OR d.road_name ILIKE '%' || :road || '%') "
            "AND COALESCE(d.latest_area_m2, 0) >= :amin AND (:st = '' OR d.status::text = :st) "
            "AND (:ids = '' OR d.defect_id = ANY(string_to_array(:ids, ','))) "
            "ORDER BY d.latest_area_m2 DESC NULLS LAST LIMIT :lim",
            {
                "road": road_name or "",
                "amin": float(min_area_m2),
                "st": status or "",
                "lim": int(min(limit, 200)),
                "ids": ",".join(defect_ids or []),
            },
        )
        return rows

    def cluster_into_packages(self, defect_ids: list[str], max_gap_m: float = 30.0) -> list[dict]:
        """Group defects into work packages: same road segment, contiguous chainage (gap <= max_gap_m).
        Computes exposure score and priority deterministically (agent design §5) and stores draft packages."""
        rows = self._validate_defects(defect_ids)
        rows.sort(key=lambda r: (r["road_segment_id"], r["chainage_m"]))
        groups: list[list[dict]] = []
        for r in rows:
            g = groups[-1] if groups else None
            if (
                g
                and g[-1]["road_segment_id"] == r["road_segment_id"]
                and r["chainage_m"] - g[-1]["chainage_m"] <= max_gap_m
            ):
                g.append(r)
            else:
                groups.append([r])
        out = []
        for g in groups:
            measured = [r for r in g if r["measurement_status"] == "measured" and r["latest_area_m2"] is not None]
            area = sum(r["latest_area_m2"] for r in measured)
            worst = max(g, key=lambda r: SEVERITY_W[r["latest_severity"]])["latest_severity"]
            ctx = self.lookup_context(g[0]["defect_id"])
            road_w = 0.6 if g[0]["is_control"] else ROAD_W.get(g[0]["hierarchy"], 1.0)
            attrs = [
                json.loads(r["attributes"]) if isinstance(r["attributes"], str) else (r["attributes"] or {}) for r in g
            ]
            wheel = any(a.get("wheel_path") for a in attrs)
            water = any(a.get("water_pooling") for a in attrs)
            exposure = (
                SEVERITY_W[worst]
                * (1 + math.log1p(area))
                * road_w
                * (
                    1
                    + 0.5 * (ctx["schools_150m"] > 0)
                    + 0.5 * (ctx["hospitals_150m"] > 0)
                    + 0.3 * (ctx["bus_stops_50m"] > 0)
                )
                * (1.3 if wheel else 1.0)
                * (1.2 if water else 1.0)
            )
            near_sensitive = ctx["schools_150m"] > 0 or ctx["hospitals_150m"] > 0
            priority = (
                1 if exposure >= 12 or (worst == "high" and wheel and near_sensitive) else 2 if exposure >= 5 else 3
            )
            conf = min(min(r["detection_confidence"] for r in g), min(r["severity_confidence"] for r in g))
            pid = new_id()
            ids = [r["defect_id"] for r in g]
            self.reg.sql(
                "INSERT INTO work_package (package_id, road_segment_id, defect_ids, total_area_m2, priority, "
                "exposure_score, confidence, state, agent_run_id) VALUES (:p, :seg, string_to_array(:ids, ','), "
                ":a, :pr, :e, :c, 'draft', :run)",
                {
                    "p": pid,
                    "seg": g[0]["road_segment_id"],
                    "ids": ",".join(ids),
                    "a": round(area, 4),
                    "pr": priority,
                    "e": round(exposure, 3),
                    "c": round(conf, 3),
                    "run": self.run_id,
                },
            )
            out.append(
                {
                    "package_id": pid,
                    "road_name": g[0]["road_name"],
                    "defect_ids": ids,
                    "chainage_from_m": round(g[0]["chainage_m"], 1),
                    "chainage_to_m": round(g[-1]["chainage_m"], 1),
                    "total_area_m2": round(area, 3),
                    "not_measured": len(g) - len(measured),
                    "worst_severity": worst,
                    "exposure_score": round(exposure, 2),
                    "priority": priority,
                    "confidence": round(conf, 3),
                    "below_confidence_floor": conf < CONFIDENCE_FLOOR,
                    "context": ctx,
                }
            )
        return out

    def lookup_context(self, defect_id: str) -> dict:
        """Schools/hospitals within 150 m and bus stops within 50 m of a defect (PostGIS, OSM POIs)."""
        self._validate_defects([defect_id])
        r = self.reg.sql(
            "SELECT "
            "count(*) FILTER (WHERE p.kind = 'school' AND ST_DWithin(p.geom::geography, d.geom::geography, 150)) "
            "AS schools_150m, "
            "count(*) FILTER (WHERE p.kind = 'hospital' AND ST_DWithin(p.geom::geography, d.geom::geography, 150)) "
            "AS hospitals_150m, "
            "count(*) FILTER (WHERE p.kind = 'bus_stop' AND ST_DWithin(p.geom::geography, d.geom::geography, 50)) "
            "AS bus_stops_50m "
            "FROM defect d CROSS JOIN poi p WHERE d.defect_id = :d",
            {"d": defect_id},
        )[0]
        return {k: int(v) for k, v in r.items()}

    def estimate_materials(self, package_id: str, thickness_m: float = 0.05) -> dict:
        """Hot-mix quantity for a package: measured area x thickness x density x (1 + wastage).
        Depth is NOT measured; thickness is a stated assumption (0.02-0.15 m)."""
        if not 0.02 <= thickness_m <= 0.15:
            raise ToolError("OUT_OF_RANGE", "thickness_m must be between 0.02 and 0.15")
        p = self._package(package_id)
        area = float(p["total_area_m2"] or 0)
        vol = area * thickness_m
        mat = {
            "total_area_m2": round(area, 3),
            "patch_thickness_m": thickness_m,
            "volume_m3": round(vol, 4),
            "mass_t": round(vol * HOT_MIX_DENSITY_T_M3 * (1 + WASTAGE_PCT / 100), 4),
            "wastage_pct": WASTAGE_PCT,
            "assumption": "area x stated thickness; depth NOT measured; detected-but-unmeasured defects excluded",
        }
        self.reg.sql(
            "UPDATE work_package SET material = CAST(:m AS jsonb) WHERE package_id = :p",
            {"m": json.dumps(mat), "p": package_id},
        )
        return mat

    def draft_work_order(self, package_id: str, rationale: str) -> dict:
        """Write the work order (Markdown) for a package. All numbers come from the database by ID; the
        model supplies only the rationale text."""
        p = self._package(package_id)
        rows = self._validate_defects(p["defect_ids"])
        mat = json.loads(p["material"]) if isinstance(p.get("material"), str) else p.get("material")
        lines = [
            f"# Work order (DRAFT, awaiting approval): package `{package_id}`",
            "",
            f"**Road:** {rows[0]['road_name']} · **Priority:** {p['priority']} · "
            f"**Exposure score:** {p['exposure_score']} · **Confidence:** {p['confidence']}",
            "",
            "| Defect ID | Chainage (m) | Area (m²) | ± | Severity | Measurement |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(rows, key=lambda r: r["chainage_m"]):
            area = "–" if r["latest_area_m2"] is None else f"{r['latest_area_m2']:.2f}"
            unc = "–" if r["area_uncertainty_m2"] is None else f"{r['area_uncertainty_m2']:.2f}"
            lines.append(
                f"| `{r['defect_id']}` | {r['chainage_m']:.0f} | {area} | {unc} | {r['latest_severity']} | "
                f"{r['measurement_status']} |"
            )
        if mat:
            lines += [
                "",
                f"**Materials:** {mat['volume_m3']} m³ hot-mix ≈ {mat['mass_t']} t "
                f"(incl. {mat['wastage_pct']}% wastage). _Assumption: {mat['assumption']}._",
            ]
        if (p["confidence"] or 0) < CONFIDENCE_FLOOR:
            lines += ["", "**LOW CONFIDENCE: options presented, no recommendation.**"]
        lines += [
            "",
            "## Rationale (agent)",
            "",
            rationale.strip(),
            "",
            "_Synthetic survey data. Nothing has been filed: filing happens only after human approval._",
        ]
        text = "\n".join(lines)
        key = f"workorders/{self.run_id}/{package_id}.md"
        if self.artifacts_bucket:
            boto3.client("s3", region_name=REGION).put_object(Bucket=self.artifacts_bucket, Key=key, Body=text.encode())
        self.reg.sql(
            "UPDATE work_package SET rationale = :r, pdf_key = :k WHERE package_id = :p",
            {"r": rationale, "k": key, "p": package_id},
        )
        return {"package_id": package_id, "work_order_key": key, "characters": len(text)}

    def request_human_approval(self, package_id: str) -> dict:
        """Start the approval workflow. Returns only the state; the approval token stays server-side."""
        p = self._package(package_id)
        if not p.get("pdf_key"):
            raise ToolError("NOT_READY", "draft the work order before requesting approval")
        arn = None
        if self.approval_state_machine:
            arn = boto3.client("stepfunctions", region_name=REGION).start_execution(
                stateMachineArn=self.approval_state_machine,
                name=f"approve-{package_id}",
                input=json.dumps({"package_id": package_id}),
            )["executionArn"]
        self.reg.sql("UPDATE work_package SET state = 'awaiting_approval' WHERE package_id = :p", {"p": package_id})
        return {"package_id": package_id, "state": "awaiting_approval", "workflow_started": arn is not None}

    def check_existing_tickets(self, defect_ids: list[str]) -> list[dict]:
        """Work packages (and mock tickets) that already cover any of these defects, so the same pothole is
        not ordered twice. Returns one row per active package with the overlapping defect IDs."""
        self._validate_defects(defect_ids)
        rows = self.reg.sql(
            "SELECT w.package_id, w.state, w.priority, array_to_string(w.defect_ids, ',') AS ids, "
            "t.ticket_id FROM work_package w LEFT JOIN ticket t ON t.package_id = w.package_id "
            "WHERE w.state IN (SELECT unnest(string_to_array(:states, ','))) "
            "AND w.defect_ids && string_to_array(:ids, ',') ORDER BY w.created_at",
            {"states": ",".join(ACTIVE_STATES), "ids": ",".join(defect_ids)},
        )
        asked = set(defect_ids)
        return [
            {
                "package_id": r["package_id"],
                "state": r["state"],
                "priority": r["priority"],
                "ticket_id": r["ticket_id"],
                "overlapping_defect_ids": [d for d in r["ids"].split(",") if d in asked],
            }
            for r in rows
        ]

    def schedule_reinspection(self, defect_ids: list[str], reason: str, package_id: str | None = None) -> dict:
        """Ask the next survey pass to look again at these defects (low confidence, not measured, or a repair
        to confirm). One row per road segment, covering the defects' chainage +/- 20 m."""
        rows = self._validate_defects(defect_ids)
        if package_id:
            self._package(package_id)
        last = self.reg.sql("SELECT max(pass_id) AS p FROM observation")[0]["p"] or "pass0"
        due = f"after:{last}"
        out = []
        for seg in sorted({r["road_segment_id"] for r in rows}):
            ch = [r["chainage_m"] for r in rows if r["road_segment_id"] == seg]
            rid = new_id()
            self.reg.sql(
                "INSERT INTO reinspection (reinspection_id, road_segment_id, chainage_from, chainage_to, due_pass, "
                "reason, package_id) VALUES (:i, :seg, :a, :b, :due, :why, :p)",
                {
                    "i": rid,
                    "seg": seg,
                    "a": round(min(ch) - 20, 1),
                    "b": round(max(ch) + 20, 1),
                    "due": due,
                    "why": reason[:500],
                    "p": package_id,
                },
            )
            out.append(
                {
                    "reinspection_id": rid,
                    "road_segment_id": seg,
                    "chainage_from_m": round(min(ch) - 20, 1),
                    "chainage_to_m": round(max(ch) + 20, 1),
                }
            )
        return {"due": due, "scheduled": out}

    def verify_repair(self, package_id: str) -> dict:
        """Did the filed repair happen? Compares the package's defects with the latest survey pass: a defect
        that the later pass drove past without detecting is 'not seen again' (repaired); one still detected is
        open. A filed package becomes `verified` when every defect is gone, `escalated` when any remains."""
        p = self._package(package_id)
        rows = self.reg.sql(
            "SELECT d.defect_id, d.status::text AS status, d.last_seen_pass, "
            "(SELECT e.evidence::text FROM status_event e WHERE e.defect_id = d.defect_id "
            " ORDER BY e.event_id DESC LIMIT 1) AS evidence "
            "FROM defect d WHERE d.defect_id IN (SELECT unnest(string_to_array(:ids, ',')))",
            {"ids": ",".join(p["defect_ids"])},
        )
        gone = [r["defect_id"] for r in rows if r["status"] == "repaired"]
        still = [r["defect_id"] for r in rows if r["status"] != "repaired"]
        verdict = "verified" if not still else "not_yet_verified" if not gone else "partially_repaired"
        new_state = None
        if p["state"] == "filed":
            new_state = "verified" if not still else "escalated" if gone else None
            if new_state:
                self.reg.sql(
                    "UPDATE work_package SET state = :s WHERE package_id = :p", {"s": new_state, "p": package_id}
                )
        return {
            "package_id": package_id,
            "package_state_before": p["state"],
            "package_state_after": new_state or p["state"],
            "verdict": verdict,
            "not_seen_again": gone,
            "still_present": still,
            "evidence": {r["defect_id"]: json.loads(r["evidence"]) if r["evidence"] else None for r in rows},
            "note": "'not seen again' means a later pass drove past without detecting it; confirm on site if needed",
        }


def tools_from_env(run_id: str = "local") -> Tools:
    return Tools(
        Register(),
        run_id=run_id,
        approval_state_machine=os.environ.get("PATCHWORK_APPROVAL_SFN"),
        artifacts_bucket=os.environ.get("PATCHWORK_ARTIFACTS_BUCKET"),
    )
