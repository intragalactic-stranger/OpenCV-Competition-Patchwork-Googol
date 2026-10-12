"""Dashcam frame renderer: road-aligned ground tiles -> distorted 1080p camera image + exact GT masks.

The road is rendered in road-aligned coordinates (the corridor is "straightened" locally), so the
image geometry is exactly the road-plane homography of `CameraModel`. Curvature is carried by the
corridor polyline when positions are converted to lat/lon, not by the pixels.
"""

from __future__ import annotations

import dataclasses
import math
from collections import OrderedDict
from dataclasses import dataclass

import cv2
import numpy as np

from patchwork.camera import CameraModel
from patchwork.synth.world import D_MIN, RES, TILE_M, Tile, TileRenderer, World, tile_index

NEAR_MAX_M = 25.0  # 1 cm/px strip up to here
FAR_MAX_M = 300.0  # 5 cm/px strip up to here; beyond -> haze/background
FAR_FACTOR = 5
HAZE = np.array([200, 195, 190], np.float32)
HAZE_M = 180.0  # e-folding distance of aerial haze
ROADSIDE = (150, 156, 160)  # BGR beyond the textured strip (|d| > 10 m)


@dataclass
class FramePose:
    s: float  # chainage of the camera (m)
    lateral: float  # camera offset from the driving line (m, + right)
    pitch_deg: float
    roll_deg: float
    yaw_deg: float
    exposure: float = 1.0


@dataclass
class RenderedFrame:
    image: np.ndarray  # (H, W, 3) uint8 BGR
    label: np.ndarray  # (H, W) uint8 class ids
    instance: np.ndarray  # (H, W) uint16 defect index + 1


class FrameRenderer:
    def __init__(self, world: World, pass_k: int, camera: CameraModel, seed: int = 0, cache_tiles: int = 48):
        self.world = world
        self.k = pass_k
        self.cam = camera
        self.tiles = TileRenderer(world, pass_k)
        self._cache: OrderedDict[int, tuple[Tile, np.ndarray, np.ndarray, np.ndarray]] = OrderedDict()
        self._cache_n = cache_tiles
        self._grid = camera.undistorted_pixel_grid()
        self._rng = np.random.default_rng([world.seed, pass_k, seed, 3])
        H, W = camera.height, camera.width
        # car bonnet in the bottom of the frame (fixed to the camera)
        u = np.arange(W, dtype=np.float32)
        hood_top = H - 48 - 38 * (1 - ((u - W / 2) / (W * 0.62)) ** 2)
        self._hood = np.arange(H, dtype=np.float32)[:, None] > hood_top[None, :]
        vv = (np.arange(H, dtype=np.float32)[:, None] - hood_top[None, :]).clip(0, 90) / 90
        self._hood_img = np.dstack([22 + 25 * (1 - vv), 22 + 24 * (1 - vv), 24 + 22 * (1 - vv)]).astype(np.float32)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
        self._vignette = (1 - 0.22 * r2).astype(np.float32)[..., None]
        self._sky_cache: dict[tuple[str, int], np.ndarray] = {}
        self._noise = [self._rng.normal(0, 2.2, (H, W, 3)).astype(np.float32) for _ in range(4)]
        self._hood_u8 = self._hood.astype(np.uint8)
        self._hood_img_u8 = np.clip(self._hood_img, 0, 255).astype(np.uint8)

    # ----- tiles ---------------------------------------------------------------------------------
    def _tile(self, idx: int):
        if idx in self._cache:
            self._cache.move_to_end(idx)
            return self._cache[idx]
        t = self.tiles.render(idx)
        far = cv2.resize(t.image, None, fx=1 / FAR_FACTOR, fy=1 / FAR_FACTOR, interpolation=cv2.INTER_AREA)
        far_lbl = t.label[FAR_FACTOR // 2 :: FAR_FACTOR, FAR_FACTOR // 2 :: FAR_FACTOR]
        far_inst = t.instance[FAR_FACTOR // 2 :: FAR_FACTOR, FAR_FACTOR // 2 :: FAR_FACTOR]
        self._cache[idx] = (t, far, far_lbl, far_inst)
        while len(self._cache) > self._cache_n:
            self._cache.popitem(last=False)
        return self._cache[idx]

    def _strip(self, s_from: float, s_to: float, far: bool):
        i0, i1 = tile_index(max(s_from, 0.0)), tile_index(min(s_to, self.world.corridor.length_m - 1e-3))
        parts = [self._tile(i) for i in range(i0, i1 + 1)]
        if far:
            img = np.concatenate([p[1] for p in parts])
            lbl = np.concatenate([p[2] for p in parts])
            ins = np.concatenate([p[3] for p in parts])
        else:
            img = np.concatenate([p[0].image for p in parts])
            lbl = np.concatenate([p[0].label for p in parts])
            ins = np.concatenate([p[0].instance for p in parts])
        return i0 * TILE_M, img, lbl, ins

    # ----- background ----------------------------------------------------------------------------
    def _background(self, kind: str, horizon_v: float) -> np.ndarray:
        H, W = self.cam.height, self.cam.width
        key = (kind, int(round(horizon_v)))
        if key in self._sky_cache:
            return self._sky_cache[key]
        v = np.arange(H, dtype=np.float32)[:, None]
        if kind == "tunnel":
            base = np.full((H, W, 3), 38, np.float32)
            base += 18 * np.exp(-(((v - horizon_v) / 120) ** 2))[..., None]
            lights = (np.abs(v - (horizon_v - 140)) < 6) & (np.mod(np.arange(W), 160) < 70)[None, :]
            base[lights] = (120, 190, 235)
        else:
            t = np.clip((horizon_v - v) / max(horizon_v, 1), 0, 1)
            top, low = np.array([205, 170, 140], np.float32), np.array([215, 210, 205], np.float32)
            base = (low * (1 - t) + top * t)[..., None, :].repeat(W, axis=1).reshape(H, W, 3)
            base[(v >= horizon_v)[:, 0]] = HAZE
            if kind != "control":
                rng = np.random.default_rng(hash(kind) & 0xFFFF)
                heights = np.repeat(rng.integers(20, 160, W // 40 + 1), 40)[:W].astype(np.float32)
                sky = v < horizon_v
                bld = sky & (v > horizon_v - heights[None, :])
                shade = 115 + 30 * np.repeat(rng.random(W // 40 + 1), 40)[:W][None, :]
                base[bld] = np.broadcast_to(shade, (H, W))[bld][:, None] * np.array([0.95, 1.0, 1.05], np.float32)
        base = np.clip(base, 0, 255).astype(np.uint8)
        self._sky_cache[key] = base
        return base

    # ----- frame ---------------------------------------------------------------------------------
    def render(self, pose: FramePose, add_noise: bool = True, with_truth: bool = True) -> RenderedFrame:
        cam = dataclasses.replace(self.cam, pitch_deg=pose.pitch_deg, roll_deg=pose.roll_deg, yaw_deg=pose.yaw_deg)
        H, W = cam.height, cam.width
        X, Y, valid = cam.ground_from_grid(self._grid)
        valid &= ~self._hood
        prof = self.world.profile_at(min(pose.s + 10, self.world.corridor.length_m - 1e-3))
        kind = "tunnel" if prof.key == "tunnel" else "control" if prof.key == "control" else "city"
        img = self._background(kind, cam.horizon_v()).copy()
        label = np.zeros((H, W), np.uint8)
        inst = np.zeros((H, W), np.uint16)

        Yc = np.where(valid, Y, np.float32(1e6))
        near = (Yc <= NEAR_MAX_M).astype(np.uint8)
        far = ((Yc > NEAR_MAX_M) & (Yc <= FAR_MAX_M)).astype(np.uint8)
        y_lo = float(Yc.min()) if near.any() else 2.0
        for mask, s_from, s_to, res, is_far in (
            (near, pose.s + y_lo - 0.1, pose.s + NEAR_MAX_M + 0.1, RES, False),
            (far, pose.s + NEAR_MAX_M - 0.5, pose.s + FAR_MAX_M + 0.5, RES * FAR_FACTOR, True),
        ):
            if not mask.any() or s_from >= self.world.corridor.length_m:
                continue
            strip_s0, simg, slbl, sins = self._strip(s_from, s_to, is_far)
            map_y = (pose.s - strip_s0) / res - 0.5 + Yc / res
            map_x = (pose.lateral - D_MIN) / res - 0.5 + X / res
            map_y = map_y.astype(np.float32)
            map_x = np.nan_to_num(map_x, nan=-1e4).astype(np.float32)
            col = cv2.remap(simg, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=ROADSIDE)
            cv2.copyTo(col, mask, img)
            if not with_truth:
                continue
            lb = cv2.remap(slbl, map_x, map_y, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            it = cv2.remap(sins, map_x, map_y, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            cv2.copyTo(lb, mask, label)
            cv2.copyTo(it, mask, inst)
        cv2.copyTo(self._hood_img_u8, self._hood_u8, img)

        # photometrics in one float pass: haze (ground only), vignette, exposure, tint, noise
        ground = Yc <= FAR_MAX_M
        h = np.zeros((H, W), np.float32)
        h[ground] = 1 - np.exp(-Yc[ground] / HAZE_M)
        gain = pose.exposure * (0.62 if kind == "tunnel" else 1.0)
        a = (1 - h) * self._vignette[..., 0] * gain
        f = img.astype(np.float32)
        f *= a[..., None]
        f += (h * self._vignette[..., 0] * gain)[..., None] * HAZE
        if kind == "tunnel":
            f *= np.array([0.75, 0.92, 1.1], np.float32)
        f = cv2.GaussianBlur(f, (0, 0), 0.6)
        if add_noise:
            f += self._noise[int(self._rng.integers(len(self._noise)))]
        out = np.clip(f, 0, 255).astype(np.uint8)
        label[~valid] = 0
        inst[~valid] = 0
        return RenderedFrame(out, label, inst)


def visible_defects(inst: np.ndarray) -> dict[int, int]:
    """{defect index: visible pixel count} from an instance mask."""
    ids, counts = np.unique(inst[inst > 0], return_counts=True)
    return {int(i) - 1: int(c) for i, c in zip(ids, counts, strict=True)}


def default_pose(s: float) -> FramePose:
    return FramePose(s=s, lateral=0.0, pitch_deg=CameraModel().pitch_deg, roll_deg=0.0, yaw_deg=0.0)


__all__ = ["FramePose", "FrameRenderer", "RenderedFrame", "visible_defects", "default_pose", "math"]
