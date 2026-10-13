"""The defect contract: pydantic models and the PostGIS DDL must agree, and the rules must hold."""

import datetime as dt
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from patchwork.schema.models import (
    Defect,
    DefectType,
    Material,
    MeasurementStatus,
    Observation,
    Severity,
    severity_v1,
)

DDL = (Path(__file__).resolve().parents[1] / "src" / "patchwork" / "schema" / "ddl.sql").read_text()


def ddl_columns(table: str) -> set[str]:
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", DDL, re.S).group(1)
    cols = set()
    for line in body.splitlines():
        m = re.match(r"\s+([a-z_0-9]+)\s+\S", line)
        if m and m.group(1) not in {"CHECK"}:
            cols.add(m.group(1))
    return cols


@pytest.mark.parametrize("model,table", [(Observation, "observation"), (Defect, "defect")])
def test_models_match_ddl(model, table):
    missing = set(model.model_fields) - ddl_columns(table)
    assert not missing, f"{table} lacks columns for {missing}"


def _obs(**kw):
    base = dict(
        pass_id="p1",
        clip_id="c1",
        frame_idx=3,
        frame_ts=dt.datetime(2026, 10, 13, tzinfo=dt.UTC),
        lat=18.9,
        lon=72.8,
        gnss_hdop_proxy=3.0,
        road_segment_id="seg000",
        road_name="Marine Drive",
        chainage_m=10.0,
        lateral_offset_m=0.5,
        area_m2=0.4,
        area_uncertainty_m2=0.03,
        length_m=0.8,
        width_m=0.6,
        measurement_status=MeasurementStatus.measured,
        severity=Severity.medium,
        severity_confidence=0.8,
        detection_confidence=0.9,
        material=Material.for_area(0.4),
        calibration_id="cam01-v1",
        model_version="seg-v1",
        pipeline_version="0.1",
        privacy_blurred=True,
    )
    base.update(kw)
    return Observation(**base)


def test_observation_rules():
    assert _obs().obs_id
    with pytest.raises(ValidationError):
        _obs(privacy_blurred=False)
    with pytest.raises(ValidationError):
        _obs(area_m2=None)  # measured but no area
    _obs(area_m2=None, measurement_status=MeasurementStatus.detected_not_measured, material=None)


def test_material_and_severity():
    m = Material.for_area(1.0)
    assert m.volume_m3 == pytest.approx(0.05) and m.mass_t == pytest.approx(0.05 * 2.35 * 1.1, rel=1e-3)
    assert severity_v1(0.1, DefectType.pothole, 0.3)[0] == Severity.low
    assert severity_v1(0.1, DefectType.pothole, 0.3, wheel_path=True)[0] == Severity.medium
    assert severity_v1(0.5, DefectType.pothole, 0.9)[0] == Severity.medium
    assert severity_v1(0.5, DefectType.pothole, 0.9, water=True)[0] == Severity.high
    assert severity_v1(1.2, DefectType.pothole, 1.5)[0] == Severity.high
    assert severity_v1(0.3, DefectType.edge_break, 2.5)[0] == Severity.high
    assert severity_v1(None, DefectType.pothole, None)[0] == Severity.medium
