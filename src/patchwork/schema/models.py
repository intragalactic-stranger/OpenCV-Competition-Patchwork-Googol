"""Defect record schema v1: the contract between perception, the register and the agent.

Mirrors main_docs/plan/05-defect-record-schema.md and schema/ddl.sql; tests/test_schema.py keeps them in sync.
Changes after the `schema-v1` tag are additive only (new nullable fields) and need a decision-log entry.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator
from ulid import ULID

SCHEMA_VERSION = "v1"
PATCH_THICKNESS_M = 0.05
HOT_MIX_DENSITY_T_M3 = 2.35
WASTAGE_PCT = 10.0


class DefectType(StrEnum):
    pothole = "pothole"
    edge_break = "edge_break"
    depression = "depression"


class MeasurementStatus(StrEnum):
    measured = "measured"
    detected_not_measured = "detected_not_measured"
    obscured = "obscured"


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class DefectStatus(StrEnum):
    new = "new"
    unchanged = "unchanged"
    repaired = "repaired"
    degraded = "degraded"
    obscured = "obscured"


def new_id() -> str:
    return str(ULID())


class Material(BaseModel):
    patch_thickness_m: float = PATCH_THICKNESS_M
    volume_m3: float
    mass_t: float
    wastage_pct: float = WASTAGE_PCT
    assumption: str = "area x stated thickness; depth NOT measured"

    @classmethod
    def for_area(cls, area_m2: float, thickness_m: float = PATCH_THICKNESS_M) -> Material:
        vol = area_m2 * thickness_m
        return cls(
            patch_thickness_m=thickness_m,
            volume_m3=round(vol, 4),
            mass_t=round(vol * HOT_MIX_DENSITY_T_M3 * (1 + WASTAGE_PCT / 100), 4),
        )


class Observation(BaseModel):
    obs_id: str = Field(default_factory=new_id)
    defect_id: str | None = None
    pass_id: str
    clip_id: str
    frame_idx: int
    frame_ts: dt.datetime
    lat: float
    lon: float
    gnss_hdop_proxy: float
    road_segment_id: str
    road_name: str
    chainage_m: float
    lateral_offset_m: float
    defect_type: DefectType = DefectType.pothole
    area_m2: float | None
    area_uncertainty_m2: float | None
    length_m: float | None
    width_m: float | None
    measurement_status: MeasurementStatus
    severity: Severity
    severity_confidence: float = Field(ge=0, le=1)
    detection_confidence: float = Field(ge=0, le=1)
    material: Material | None
    attributes: dict = Field(default_factory=dict)
    crop_key: str | None = None
    overlay_key: str | None = None
    rectified_key: str | None = None
    calibration_id: str
    model_version: str
    pipeline_version: str
    privacy_blurred: bool
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @model_validator(mode="after")
    def _rules(self) -> Observation:
        # the same rules the database enforces with CHECK constraints (ddl.sql)
        if not self.privacy_blurred:
            raise ValueError("privacy_blurred must be true before an observation is stored")
        if (self.measurement_status == MeasurementStatus.measured) != (self.area_m2 is not None):
            raise ValueError("area_m2 must be set exactly when measurement_status == measured")
        return self


class Defect(BaseModel):
    defect_id: str = Field(default_factory=new_id)
    first_seen_pass: str
    last_seen_pass: str
    status: DefectStatus = DefectStatus.new
    status_confidence: float = 1.0
    latest_obs_id: str
    lat: float
    lon: float
    road_segment_id: str
    road_name: str
    chainage_m: float
    latest_area_m2: float | None
    latest_severity: Severity
    open_work_package_id: str | None = None


def severity_v1(
    area_m2: float | None, kind: DefectType, length_m: float | None, wheel_path: bool = False, water: bool = False
) -> tuple[Severity, float]:
    """Area-based rules (05 §6), before calibration. Returns (band, confidence)."""
    if area_m2 is None:
        return Severity.medium, 0.3  # detected but not measured: never silently "low"
    if area_m2 >= 1.0 or (kind == DefectType.edge_break and (length_m or 0) > 2.0):
        band = Severity.high
    elif area_m2 >= 0.25 or wheel_path:
        band = Severity.high if water else Severity.medium
    else:
        band = Severity.low
    edges = [0.25, 1.0]
    margin = min(abs(area_m2 - e) / e for e in edges)  # far from a threshold -> confident
    return band, round(min(1.0, 0.6 + margin), 2)
