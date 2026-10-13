"""Perception stages that do not need a trained model: triage odometry and privacy blur."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from patchwork.camera import CameraModel
from patchwork.perception.privacy import YUNET, BlurredFrame, Privacy, Region, blur_region, find_plates
from patchwork.perception.triage import Triage, TriageConfig
from patchwork.synth.corridor import load_corridor
from patchwork.synth.render import FramePose, FrameRenderer
from patchwork.synth.world import build_world

ROOT = Path(__file__).resolve().parents[1]
CORRIDOR = ROOT / "data" / "corridor"
needs_corridor = pytest.mark.skipif(not (CORRIDOR / "corridor.npz").exists(), reason="run corridor build first")
needs_yunet = pytest.mark.skipif(not YUNET.exists(), reason="run `make smoke` to download YuNet")


@needs_corridor
def test_triage_odometry_and_spacing():
    """Constant 10 m/s for 3 s then a stop: distance within 5 %, no travel while stopped, ~3 m spacing."""
    world = build_world(load_corridor(CORRIDOR), seed=7, n_passes=1)
    cam = CameraModel()
    r = FrameRenderer(world, 1, cam)
    fps, v = 15.0, 10.0
    s = [1500 + v * i / fps for i in range(45)] + [1500 + v * 44 / fps] * 8
    tri = Triage(cam, fps, TriageConfig(spacing_m=3.0))
    for si in s:
        tri.push(r.render(FramePose(si, 0.0, 8.0, 0.0, 0.0, 1.0)).image)
    res = tri.result
    est = np.array([x.travel_m for x in res.scores])
    assert abs(est[:45].sum() - v * 44 / fps) / (v * 44 / fps) < 0.05
    assert (est[45:] == 0).all()
    kept_s = np.array(s)[res.kept]
    assert len(res.kept) >= 9 and np.diff(kept_s).min() >= 2.0


def _with_plate(img: np.ndarray, x: int, y: int, w: int) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    g, h = img.copy(), int(w / 4.5)
    cv2.rectangle(g, (x, y), (x + w, y + h), (235, 235, 235), -1)
    cv2.rectangle(g, (x, y), (x + w, y + h), (20, 20, 20), 2)
    cv2.putText(g, "MH01AB1234", (x + int(0.05 * w), y + int(0.75 * h)), 0, w / 260, (15, 15, 15), max(1, w // 80))
    return g, (x, y, w, h)


def _road(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = cv2.GaussianBlur(rng.normal(95, 18, (1080, 1920)).astype(np.float32), (0, 0), 2)
    return cv2.cvtColor(np.clip(base, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


@pytest.mark.parametrize("w", [80, 110, 160, 220])
def test_injected_plate_is_found_and_unreadable(w):
    img, (x, y, pw, ph) = _with_plate(_road(), 700, 600, w)
    plates = find_plates(img)
    assert any(abs(r.box[0] - x) < 0.3 * pw and abs(r.box[1] - y) < ph for r in plates)
    out = img.copy()
    for r in plates:
        blur_region(out, r.box)
    text = (slice(y + 3, y + ph - 3), slice(x + 3, x + pw - 3))
    assert cv2.Laplacian(out[text], cv2.CV_64F).var() < 0.25 * cv2.Laplacian(img[text], cv2.CV_64F).var()


def test_plain_road_texture_has_no_plates():
    assert find_plates(_road(1)) == []


def test_blurred_frame_reports_overlaps():
    bf = BlurredFrame(np.zeros((10, 10, 3), np.uint8), (Region("face", (2, 2, 3, 3), 0.9),))
    assert bf.overlaps((4, 4, 2, 2)) and not bf.overlaps((6, 6, 2, 2))


@needs_yunet
def test_privacy_runs_on_blank_frame():
    out = Privacy().apply(np.full((1080, 1920, 3), 120, np.uint8))
    assert isinstance(out, BlurredFrame) and out.regions == ()


def test_windowed_bev_warp_matches_full_warp():
    from patchwork.perception.ipm import IPM

    ipm = IPM(CameraModel())
    m = np.zeros((1080, 1920), np.uint8)
    cv2.ellipse(m, (1100, 650), (60, 20), 15, 0, 360, 1, -1)
    cv2.ellipse(m, (500, 820), (140, 40), -10, 0, 360, 1, -1)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    for k in range(1, n):
        comp = lab == k
        assert (ipm.warp_mask(comp) == ipm.warp_mask_box(comp, tuple(int(v) for v in stats[k, :4]))).all()
