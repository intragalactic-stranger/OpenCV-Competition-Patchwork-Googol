"""Ground-truth integrity of the synthetic world. If these fail, every downstream metric is meaningless."""

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from patchwork.camera import CameraModel
from patchwork.synth.world import (
    PATCH_LABEL,
    RES,
    STRIP_COLS,
    TILE_ROWS,
    Defect,
    TileRenderer,
    _blob,
    build_world,
    coverage,
    tile_index,
)

ROOT = Path(__file__).resolve().parents[1]
CORRIDOR = ROOT / "data" / "corridor"
needs_corridor = pytest.mark.skipif(not (CORRIDOR / "corridor.npz").exists(), reason="run corridor build first")


@pytest.mark.parametrize("pitch,roll,yaw", [(8.0, 0.0, 0.0), (8.4, 0.6, -1.5), (7.5, -0.4, 2.0)])
def test_camera_ground_roundtrip(pitch, roll, yaw):
    cam = dataclasses.replace(CameraModel(), pitch_deg=pitch, roll_deg=roll, yaw_deg=yaw)
    pts = np.array([[0, 3], [1.5, 5], [-2, 10], [3, 15], [-4, 12]], float)
    assert np.abs(cam.pixel_to_ground(cam.ground_to_pixel(pts)) - pts).max() < 1e-6


def test_camera_grid_lookup_matches_direct():
    cam = CameraModel()
    X, Y, valid = cam.ground_from_grid(cam.undistorted_pixel_grid())
    v, u = 800, 1200
    g = cam.pixel_to_ground(np.array([[u, v]], float))[0]
    assert valid[v, u]
    assert abs(X[v, u] - g[0]) < 1e-3 and abs(Y[v, u] - g[1]) < 1e-3


def test_blob_has_exact_area():
    rng = np.random.default_rng(0)
    for a in (0.05, 0.3, 1.7):
        assert abs(Defect.area(_blob(rng, a, 1.6, 0.4, 0.2)) - a) < 1e-9


def test_coverage_raster_area_unbiased():
    rng = np.random.default_rng(1)
    errs = []
    for _ in range(30):
        area = float(rng.uniform(0.05, 1.5))
        poly = _blob(rng, area, rng.uniform(1, 2), rng.uniform(0, 3), 0.15) + np.array([4.0, rng.uniform(-3, 3)])
        rs, cs, cov = coverage(poly, 0.0, TILE_ROWS, STRIP_COLS)
        errs.append(((cov >= 0.5).sum() * RES * RES - area) / area)
    assert abs(np.mean(errs)) < 0.01 and np.max(np.abs(errs)) < 0.03


@needs_corridor
def test_world_lifecycle_and_tiles_deterministic():
    from patchwork.synth.corridor import load_corridor

    c = load_corridor(CORRIDOR)
    w1, w2 = build_world(c, seed=3, n_passes=3), build_world(c, seed=3, n_passes=3)
    assert [d.truth_id for d in w1.defects] == [d.truth_id for d in w2.defects]
    for d in w1.defects:
        assert set(d.states) == {1, 2, 3}
        seq = [d.states[k] for k in (1, 2, 3)]
        if "repaired" in seq:  # once repaired, stays repaired (re-failure not modelled yet)
            assert all(x == "repaired" for x in seq[seq.index("repaired") :])
    # no defects on the control section (Coastal Road), by design
    assert not any(c.segment_at(float(d.poly[:, 0].mean())).is_control for d in w1.defects)
    d = next(x for x in w1.defects if x.states[1] == "present")
    ti = tile_index(float(d.poly[:, 0].mean()))
    a, b = TileRenderer(w1, 1).render(ti), TileRenderer(w2, 1).render(ti)
    assert np.array_equal(a.image, b.image) and np.array_equal(a.instance, b.instance)


@needs_corridor
def test_repaired_defect_renders_as_patch_not_defect():
    from patchwork.synth.corridor import load_corridor

    w = build_world(load_corridor(CORRIDOR), seed=7, n_passes=3)
    i, d = next((i, d) for i, d in enumerate(w.defects) if d.states[2] == "repaired" and d.states[1] == "present")
    ti = tile_index(float(d.poly[:, 0].mean()))
    before, after = TileRenderer(w, 1).render(ti), TileRenderer(w, 2).render(ti)
    assert (before.instance == i + 1).any()
    assert not (after.instance == i + 1).any()
    assert (after.label == PATCH_LABEL).any()


@needs_corridor
def test_corridor_shape():
    seg = json.loads((CORRIDOR / "segments.json").read_text())
    total = seg[-1]["chainage_end_m"]
    control = sum(s["chainage_end_m"] - s["chainage_start_m"] for s in seg if s["is_control"])
    assert 24_000 < total < 32_000
    assert 8_000 < control < 12_000
