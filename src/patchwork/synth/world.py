"""Procedural road world in road-aligned metric coordinates.

Coordinates
  s : chainage along the corridor polyline (m)  -> rows of the ground texture
  d : lateral offset from the survey vehicle's driving line, + = right (m) -> columns
The texture is rasterised in tiles of TILE_M metres at RES metres/pixel. Persistent features are the
same on every pass; defects follow a seeded lifecycle; shadows and wet patches change per pass.

Ground truth is exact by construction: a defect *is* its polygon, so its area is the polygon area.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from patchwork.synth.corridor import Corridor, Segment

RES = 0.01  # metres per texture pixel (1 cm)
TILE_M = 8.0
TILE_ROWS = int(round(TILE_M / RES))
D_MIN, D_MAX = -10.0, 10.0  # lateral extent of the textured ground strip
STRIP_COLS = int(round((D_MAX - D_MIN) / RES))

CLASS_IDS = {"background": 0, "pothole": 1, "edge_break": 2, "depression": 3}
PATCH_LABEL = 10  # repaired patch in the auxiliary label (not a defect class)


# ---------------------------------------------------------------------------------------------
# Road profiles
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RoadProfile:
    key: str
    n_lanes: int
    vehicle_lane: int  # 0 = leftmost lane (India drives on the left)
    lane_w: float
    asphalt: tuple[float, float, float]  # base albedo, BGR 0..1
    wear: float  # amplitude of low-frequency tone variation
    marking_alpha: float  # paint visibility (faded on old roads)
    dash: tuple[float, float]  # dash length, gap (m)
    left_side: str  # kerb | parapet | median
    defects_per_km: float
    seams_per_km: float
    patches_per_km: float
    manholes_per_km: float
    breakers_per_km: float
    speed_kmh: float

    def edges(self) -> tuple[float, float]:
        """Left and right carriageway edges relative to the driving line."""
        left = -(self.vehicle_lane + 0.5) * self.lane_w
        return left, left + self.n_lanes * self.lane_w

    def lane_centres(self) -> list[float]:
        left, _ = self.edges()
        return [left + (i + 0.5) * self.lane_w for i in range(self.n_lanes)]


PROFILES: dict[str, RoadProfile] = {
    "control": RoadProfile(
        "control", 4, 1, 3.5, (0.27, 0.27, 0.26), 0.04, 0.95, (3.0, 6.0), "parapet", 0.0, 2.0, 0.0, 0.0, 0.0, 70.0
    ),
    "tunnel": RoadProfile(
        "tunnel", 3, 1, 3.5, (0.24, 0.24, 0.23), 0.03, 0.9, (3.0, 6.0), "parapet", 0.0, 1.0, 0.0, 0.0, 0.0, 60.0
    ),
    "primary": RoadProfile(
        "primary", 3, 1, 3.5, (0.40, 0.41, 0.42), 0.10, 0.6, (3.0, 4.5), "kerb", 10.0, 10.0, 4.0, 2.5, 0.3, 40.0
    ),
    "secondary": RoadProfile(
        "secondary", 2, 0, 3.3, (0.43, 0.44, 0.45), 0.13, 0.45, (2.0, 4.0), "kerb", 14.0, 14.0, 6.0, 3.0, 0.8, 30.0
    ),
}


def profile_for(seg: Segment) -> RoadProfile:
    if seg.is_tunnel:
        return PROFILES["tunnel"]
    if seg.is_control:
        return PROFILES["control"]
    if seg.highway in ("primary", "trunk", "primary_link", "trunk_link", "motorway_link"):
        return PROFILES["primary"]
    return PROFILES["secondary"]


# ---------------------------------------------------------------------------------------------
# Deterministic hash noise
# ---------------------------------------------------------------------------------------------
def _hash01(i: np.ndarray, j: np.ndarray, seed: int) -> np.ndarray:
    """splitmix64 over (i, j, seed) -> float32 in [0, 1). Same lattice point -> same value, always."""
    x = (i.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)) ^ (j.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F))
    x ^= np.uint64(seed * 0x165667B19E3779F9 & 0xFFFFFFFFFFFFFFFF)
    x ^= x >> np.uint64(30)
    x *= np.uint64(0xBF58476D1CE4E5B9)
    x ^= x >> np.uint64(27)
    x *= np.uint64(0x94D049BB133111EB)
    x ^= x >> np.uint64(31)
    return (x >> np.uint64(40)).astype(np.float32) / np.float32(1 << 24)


def value_noise(row0: int, n_rows: int, n_cols: int, cell_px: float, seed: int) -> np.ndarray:
    """Smooth noise in [-1, 1] on the global (row, col) lattice; continuous across tile borders."""
    i0 = math.floor(row0 / cell_px) - 1
    i1 = math.ceil((row0 + n_rows) / cell_px) + 2
    j1 = math.ceil(n_cols / cell_px) + 2
    ii, jj = np.meshgrid(np.arange(i0, i1), np.arange(-1, j1), indexing="ij")
    lattice = _hash01(ii - np.int64(-(1 << 40)), jj + 7, seed) * 2 - 1
    rows = (np.arange(n_rows, dtype=np.float32) + row0) / cell_px - i0
    cols = np.arange(n_cols, dtype=np.float32) / cell_px + 1
    mx, my = np.meshgrid(cols, rows)
    return cv2.remap(lattice.astype(np.float32), mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


# ---------------------------------------------------------------------------------------------
# World objects
# ---------------------------------------------------------------------------------------------
@dataclass
class Defect:
    truth_id: str
    kind: str  # pothole | edge_break | depression
    poly: np.ndarray  # (N, 2) vertices as (s, d) metres, pass-1 shape
    born_pass: int = 1
    seed: int = 0
    # per pass: "present" | "repaired" | "degraded" | "absent"; degraded polygons are stored separately
    states: dict[int, str] = field(default_factory=dict)
    polys: dict[int, np.ndarray] = field(default_factory=dict)
    attrs: dict = field(default_factory=dict)  # ground-truth context: water, wheel_path, road profile

    def poly_at(self, k: int) -> np.ndarray:
        keys = [p for p in sorted(self.polys) if p <= k]
        return self.polys[keys[-1]] if keys else self.poly

    @staticmethod
    def area(poly: np.ndarray) -> float:
        s, d = poly[:, 0], poly[:, 1]
        return float(0.5 * abs(np.dot(s, np.roll(d, 1)) - np.dot(d, np.roll(s, 1))))

    def centroid(self, k: int) -> tuple[float, float]:
        p = self.poly_at(k)
        return float(p[:, 0].mean()), float(p[:, 1].mean())


@dataclass
class Feature:
    kind: str  # seam | old_patch | manhole | breaker | oil | shadow | wet
    s0: float
    s1: float
    data: dict


@dataclass
class World:
    corridor: Corridor
    seed: int
    defects: list[Defect]
    features: list[Feature]  # persistent
    pass_features: dict[int, list[Feature]]  # per-pass (shadows, wet)
    n_passes: int

    def profile_at(self, s: float) -> RoadProfile:
        return profile_for(self.corridor.segment_at(s))


def _blob(rng: np.random.Generator, area: float, aspect: float, angle: float, rough: float, n: int = 48) -> np.ndarray:
    """Irregular closed polygon (local metres) with exactly `area` m²."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = np.ones(n)
    for h in range(2, 7):
        r += rough / h * rng.normal() * np.cos(h * t + rng.uniform(0, 2 * np.pi))
    r = np.clip(r, 0.45, None)
    pts = np.stack([r * np.cos(t) * aspect, r * np.sin(t)], axis=1)
    c, s_ = math.cos(angle), math.sin(angle)
    pts = pts @ np.array([[c, s_], [-s_, c]])
    pts *= math.sqrt(area / Defect.area(pts))
    return pts


def _edge_break(rng: np.random.Generator, s0: float, left_edge: float) -> np.ndarray:
    length = rng.uniform(0.6, 3.0)
    depth = rng.uniform(0.15, 0.55)
    n = 24
    ss = np.linspace(s0, s0 + length, n)
    prof = np.sin(np.linspace(0, np.pi, n)) ** 0.6
    inner = left_edge + depth * prof * (1 + 0.25 * rng.normal(size=n)).clip(0.3, 1.6)
    inner = cv2.GaussianBlur(inner.reshape(1, -1).astype(np.float64), (1, 5), 0).ravel()
    outer = np.full(n, left_edge)
    return np.concatenate([np.stack([ss, outer], 1), np.stack([ss[::-1], inner[::-1]], 1)])


def build_world(
    corridor: Corridor,
    seed: int = 7,
    n_passes: int = 3,
    p_repair: float = 0.20,
    p_degrade: float = 0.15,
    new_per_km: float = 0.3,
) -> World:
    rng = np.random.default_rng(seed)
    defects: list[Defect] = []
    features: list[Feature] = []
    n_def = 0

    def add_defect(kind: str, poly: np.ndarray, born: int, prof: RoadProfile) -> None:
        nonlocal n_def
        d_mid = float(poly[:, 1].mean())
        wheel = any(abs(d_mid - (lc + off)) < 0.45 for lc in prof.lane_centres() for off in (-0.85, 0.85))
        attrs = {
            "water": bool(kind == "pothole" and rng.random() < 0.25),
            "wheel_path": bool(wheel),
            "profile": prof.key,
        }
        defects.append(Defect(f"T{seed:02d}-{n_def:05d}", kind, poly, born, int(rng.integers(1 << 31)), attrs=attrs))
        n_def += 1

    def make_defect(seg_prof: RoadProfile, s_lo: float, s_hi: float, born: int) -> None:
        left, right = seg_prof.edges()
        u = rng.random()
        s0 = rng.uniform(s_lo, s_hi)
        if u < 0.20 and seg_prof.left_side == "kerb":
            add_defect("edge_break", _edge_break(rng, s0, left), born, seg_prof)
            return
        kind = "depression" if u > 0.85 else "pothole"
        if kind == "pothole":
            area = float(np.clip(rng.lognormal(math.log(0.25), 0.8), 0.03, 2.5))
            shape = _blob(rng, area, rng.uniform(1.0, 2.2), rng.uniform(0, np.pi), rng.uniform(0.08, 0.22))
        else:
            area = float(rng.uniform(0.5, 3.0))
            shape = _blob(rng, area, rng.uniform(1.0, 2.5), rng.uniform(0, np.pi), 0.06)
        # lateral position: biased to wheel paths of the lanes, kept inside the carriageway
        lane = seg_prof.lane_centres()[int(rng.integers(seg_prof.n_lanes))]
        d = lane + rng.choice([-0.85, 0.85]) * (rng.random() < 0.6) + rng.normal(0, 0.5)
        half = float(np.abs(shape[:, 1]).max())
        d = float(np.clip(d, left + half + 0.05, right - half - 0.05))
        add_defect(kind, shape + np.array([s0, d]), born, seg_prof)

    for seg in corridor.segments:
        prof = profile_for(seg)
        L = seg.length_m
        a, b = seg.chainage_start_m, seg.chainage_end_m
        left, right = prof.edges()
        for _ in range(rng.poisson(prof.defects_per_km * L / 1000)):
            make_defect(prof, a, b, 1)
        for _ in range(rng.poisson(prof.seams_per_km * L / 1000)):
            s0 = rng.uniform(a, b)
            features.append(
                Feature(
                    "seam",
                    s0 - 0.5,
                    s0 + 0.5,
                    {"s": s0, "skew": rng.normal(0, 0.05), "w": rng.uniform(0.01, 0.03), "left": left, "right": right},
                )
            )
        for _ in range(rng.poisson(prof.patches_per_km * L / 1000)):
            s0, ln, wd = rng.uniform(a, b), rng.uniform(0.6, 3.0), rng.uniform(0.5, 2.0)
            d0 = rng.uniform(left + wd / 2, right - wd / 2)
            features.append(
                Feature(
                    "old_patch", s0, s0 + ln, {"d0": d0 - wd / 2, "d1": d0 + wd / 2, "tone": rng.uniform(-0.08, 0.06)}
                )
            )
        for _ in range(rng.poisson(prof.manholes_per_km * L / 1000)):
            s0, d0 = rng.uniform(a, b), rng.uniform(left + 0.6, right - 0.6)
            features.append(Feature("manhole", s0 - 0.35, s0 + 0.35, {"s": s0, "d": d0, "r": 0.3}))
        for _ in range(rng.poisson(prof.breakers_per_km * L / 1000)):
            s0 = rng.uniform(a, b)
            features.append(Feature("breaker", s0 - 0.3, s0 + 0.3, {"s": s0, "left": left, "right": right}))

    # lifecycle over passes
    for k in range(1, n_passes + 1):
        if k > 1:
            for seg in corridor.segments:
                prof = profile_for(seg)
                if prof.defects_per_km > 0:
                    for _ in range(rng.poisson(new_per_km * seg.length_m / 1000)):
                        make_defect(prof, seg.chainage_start_m, seg.chainage_end_m, k)
        for dft in defects:
            if dft.born_pass > k:
                dft.states[k] = "absent"
            elif dft.born_pass == k:
                dft.states[k] = "present"
            else:
                prev = dft.states[k - 1]
                if prev == "repaired":
                    dft.states[k] = "repaired"  # (re-failure is a later extension)
                    continue
                u = rng.random()
                if u < p_repair:
                    dft.states[k] = "repaired"
                elif u < p_repair + p_degrade:
                    dft.states[k] = "degraded"
                    grow = 1 + rng.uniform(0.15, 0.45)
                    p = dft.poly_at(k - 1)
                    c = p.mean(0)
                    dft.polys[k] = c + (p - c) * math.sqrt(grow)
                else:
                    dft.states[k] = "present"
    for dft in defects:  # defects born later did not exist on earlier passes
        for k in range(1, n_passes + 1):
            dft.states.setdefault(k, "absent")

    # per-pass appearance: shadows and wet patches
    pass_features: dict[int, list[Feature]] = {}
    for k in range(1, n_passes + 1):
        prng = np.random.default_rng([seed, k, 99])
        feats: list[Feature] = []
        for seg in corridor.segments:
            prof = profile_for(seg)
            if prof.key == "tunnel":
                continue
            left, right = prof.edges()
            for _ in range(prng.poisson(25 * seg.length_m / 1000)):
                s0 = prng.uniform(seg.chainage_start_m, seg.chainage_end_m)
                shape = _blob(prng, prng.uniform(1.0, 12.0), prng.uniform(1.0, 4.0), prng.uniform(0, np.pi), 0.25)
                d0 = prng.uniform(left - 2, right + 2)
                poly = shape + np.array([s0, d0])
                feats.append(
                    Feature(
                        "shadow",
                        poly[:, 0].min(),
                        poly[:, 0].max(),
                        {"poly": poly, "strength": prng.uniform(0.35, 0.6)},
                    )
                )
            for _ in range(prng.poisson(4 * seg.length_m / 1000)):
                s0 = prng.uniform(seg.chainage_start_m, seg.chainage_end_m)
                shape = _blob(prng, prng.uniform(0.3, 4.0), prng.uniform(1.0, 3.0), prng.uniform(0, np.pi), 0.2)
                poly = shape + np.array([s0, prng.uniform(left + 0.3, right - 0.3)])
                feats.append(Feature("wet", poly[:, 0].min(), poly[:, 0].max(), {"poly": poly}))
        pass_features[k] = feats

    defects.sort(key=lambda x: float(x.poly[:, 0].mean()))
    features.sort(key=lambda f: f.s0)
    return World(corridor, seed, defects, features, pass_features, n_passes)


# ---------------------------------------------------------------------------------------------
# Tile rasterisation
# ---------------------------------------------------------------------------------------------
def _col(d: float) -> int:
    return int(round((d - D_MIN) / RES))


def coverage(poly_sd: np.ndarray, s_tile0: float, H: int, W: int, ss: int = 8, margin_px: int = 2):
    """Exact-ish polygon coverage, rasterised at `ss`x supersampling inside the polygon's bounding box.

    Returns (row_slice, col_slice, cov) where cov is float32 in [0, 1] for that window, or None if the
    polygon misses the tile. Thresholding cov >= 0.5 gives a mask whose area matches the polygon to
    well under 1% (plain fillPoly biases edges outward by ~half a pixel)."""
    rows = (poly_sd[:, 0] - s_tile0) / RES
    cols = (poly_sd[:, 1] - D_MIN) / RES
    r0 = max(int(math.floor(rows.min())) - margin_px, 0)
    r1 = min(int(math.ceil(rows.max())) + margin_px, H)
    c0 = max(int(math.floor(cols.min())) - margin_px, 0)
    c1 = min(int(math.ceil(cols.max())) + margin_px, W)
    if r0 >= r1 or c0 >= c1:
        return None
    hh, ww = r1 - r0, c1 - c0
    big = np.zeros((hh * ss, ww * ss), np.uint8)
    # pixel (r, c) covers [r, r+1) x [c, c+1); at ss x the sub-pixel centres sit at (k + 0.5) / ss
    pts = np.stack([(cols - c0) * ss - 0.5, (rows - r0) * ss - 0.5], 1)
    cv2.fillPoly(big, [np.round(pts * 16).astype(np.int32)], 255, lineType=cv2.LINE_8, shift=4)
    cov = cv2.resize(big, (ww, hh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return slice(r0, r1), slice(c0, c1), cov


@dataclass
class Tile:
    index: int
    image: np.ndarray  # (TILE_ROWS, STRIP_COLS, 3) uint8 BGR
    label: np.ndarray  # uint8 class ids
    instance: np.ndarray  # uint16 defect index + 1 (0 = none)


_PAINT = np.array([0.88, 0.9, 0.9], np.float32)
_YELLOW = np.array([0.15, 0.75, 0.85], np.float32)
_BLACK = np.array([0.12, 0.12, 0.12], np.float32)


class TileRenderer:
    """Renders ground tiles for one pass. Tiles are deterministic in (world seed, tile index, pass)."""

    def __init__(self, world: World, pass_k: int):
        self.w = world
        self.k = pass_k
        self._def_s = (
            np.array([[d.poly_at(pass_k)[:, 0].min(), d.poly_at(pass_k)[:, 0].max()] for d in world.defects])
            if world.defects
            else np.zeros((0, 2))
        )

    @staticmethod
    def _overlapping(items, s0: float, s1: float):
        return [f for f in items if f.s1 >= s0 and f.s0 <= s1]

    def render(self, index: int) -> Tile:
        w, k = self.w, self.k
        s0 = index * TILE_M
        s1 = s0 + TILE_M
        row0 = index * TILE_ROWS
        prof = w.profile_at(min(s0 + TILE_M / 2, w.corridor.length_m - 1e-3))
        left, right = prof.edges()
        cl, cr = max(_col(left), 0), min(_col(right), STRIP_COLS)
        rng = np.random.default_rng([w.seed, index, 7])
        H, W = TILE_ROWS, STRIP_COLS
        cols_d = (D_MIN + (np.arange(W) + 0.5) * RES).astype(np.float32)
        rows_s = (s0 + (np.arange(H) + 0.5) * RES).astype(np.float32)

        # --- albedo field -----------------------------------------------------------------------
        speck = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 0.8)
        speck *= 0.06
        g = prof.wear * value_noise(row0, H, W, 400, w.seed)
        g += 0.045 * value_noise(row0, H, W, 55, w.seed + 1)
        g += 0.03 * value_noise(row0, H, W, 9, w.seed + 2)
        g += speck
        g += 1.0
        wheel = np.zeros(W, np.float32)
        for lc in prof.lane_centres():
            for off in (-0.85, 0.85):
                wheel += prof.wear * 0.25 * np.exp(-(((cols_d - lc - off) / 0.35) ** 2))
        img = np.empty((H, W, 3), np.float32)
        img[:, cl:cr] = (g[:, cl:cr] + wheel[None, cl:cr])[..., None] * np.asarray(prof.asphalt, np.float32)

        # --- outside the carriageway -------------------------------------------------------------
        if prof.left_side == "parapet":
            side = (0.55 + 0.04 * value_noise(row0, H, W, 80, w.seed + 4))[..., None] * np.array(
                [0.9, 0.9, 0.88], np.float32
            )
        else:
            paver = 0.58 + 0.05 * value_noise(row0, H, W, 30, w.seed + 3) + speck * 0.6
            joints = (np.mod(rows_s, 0.30) < 0.012)[:, None] | (np.mod(cols_d, 0.30) < 0.012)[None, :]
            paver[joints] *= 0.8
            side = paver[..., None] * np.array([0.92, 0.97, 1.0], np.float32)
        img[:, :cl] = side[:, :cl]
        img[:, cr:] = side[:, cr:]
        if prof.left_side == "kerb":
            kc0 = max(_col(left - 0.18), 0)
            yellow = np.floor(rows_s / 0.5) % 2 == 0
            shade = (0.85 + 0.15 * g[:, kc0:cl])[..., None]
            img[:, kc0:cl] = np.where(yellow[:, None, None], _YELLOW, _BLACK) * shade

        # --- persistent features -----------------------------------------------------------------
        for f in self._overlapping(w.features, s0, s1):
            if f.kind == "old_patch":
                rs = slice(max(int((f.s0 - s0) / RES), 0), min(int((f.s1 - s0) / RES), H))
                img[rs, max(_col(f.data["d0"]), 0) : min(_col(f.data["d1"]), W)] *= (1 + f.data["tone"]) * 0.97
            elif f.kind == "seam":
                rs = slice(max(int((f.s0 - s0) / RES), 0), min(int((f.s1 - s0) / RES), H))
                ds = rows_s[rs, None] - (f.data["s"] + f.data["skew"] * cols_d[None, cl:cr])
                sub = img[rs, cl:cr]
                sub[np.abs(ds) < f.data["w"]] *= 0.45
            elif f.kind == "manhole":
                rr0, rr1 = max(int((f.s0 - 0.05 - s0) / RES), 0), min(int((f.s1 + 0.05 - s0) / RES), H)
                c0, c1 = max(_col(f.data["d"] - 0.4), 0), min(_col(f.data["d"] + 0.4), W)
                if rr0 >= rr1 or c0 >= c1:
                    continue
                rr = np.hypot(rows_s[rr0:rr1, None] - f.data["s"], cols_d[None, c0:c1] - f.data["d"])
                chk = (
                    np.floor((rows_s[rr0:rr1, None] - f.data["s"]) / 0.04) + np.floor(cols_d[None, c0:c1] / 0.04)
                ) % 2
                sub = img[rr0:rr1, c0:c1]
                lid = rr < f.data["r"]
                sub[lid] = (0.30 + 0.06 * chk[lid])[:, None] * np.array([0.9, 0.95, 1.0], np.float32)
                sub[(rr >= f.data["r"]) & (rr < f.data["r"] + 0.04)] *= 0.5
            elif f.kind == "breaker":
                rr0, rr1 = max(int((f.data["s"] - 0.25 - s0) / RES), 0), min(int((f.data["s"] + 0.25 - s0) / RES), H)
                if rr0 >= rr1:
                    continue
                stripe = np.floor(cols_d[cl:cr] / 0.4) % 2 == 0
                img[rr0:rr1, cl:cr] = np.where(stripe[None, :, None], _YELLOW * 0.9, _BLACK * 0.7)

        # --- lane markings -----------------------------------------------------------------------
        alpha = (prof.marking_alpha * (0.75 + 0.25 * value_noise(row0, H, W, 70, w.seed + 5)))[..., None]
        half = int(round(0.075 / RES))

        def paint(c: int, rows_mask=None):
            a, b = max(c - half, 0), min(c + half, W)
            if a >= b:
                return
            if rows_mask is None:
                img[:, a:b] = img[:, a:b] * (1 - alpha[:, a:b]) + _PAINT * alpha[:, a:b]
            else:
                img[rows_mask, a:b] = img[rows_mask, a:b] * (1 - alpha[rows_mask, a:b]) + _PAINT * alpha[rows_mask, a:b]

        paint(_col(left + 0.15))
        paint(_col(right - 0.15))
        dash_len, gap = prof.dash
        on = np.mod(rows_s, dash_len + gap) < dash_len
        for i in range(1, prof.n_lanes):
            paint(_col(left + i * prof.lane_w), on)

        # --- defects (this pass) -----------------------------------------------------------------
        label = np.zeros((H, W), np.uint8)
        inst = np.zeros((H, W), np.uint16)
        asphalt = np.asarray(prof.asphalt, np.float32)
        hits = (
            np.where((self._def_s[:, 1] >= s0 - 0.2) & (self._def_s[:, 0] <= s1 + 0.2))[0] if len(self._def_s) else []
        )
        for i in hits:
            d = w.defects[i]
            state = d.states.get(k, "absent")
            if state == "absent":
                continue
            poly = d.poly_at(k)
            if state == "repaired":
                c = poly.mean(0)
                lo, hi = poly.min(0) - 0.08, poly.max(0) + 0.08
                rect = np.array([[lo[0], lo[1]], [lo[0], hi[1]], [hi[0], hi[1]], [hi[0], lo[1]]]) - c
                ang = np.random.default_rng(d.seed).normal(0, 0.06)
                rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
                cv_ = coverage(rect @ rot.T + c, s0, H, W, ss=2)
                if cv_ is None:
                    continue
                rs, cs, cov = cv_
                nh, nw = cov.shape
                fresh = (
                    (0.80 + 0.05 * value_noise(row0 + rs.start, nh, nw, 6, d.seed % 9973))[..., None] * asphalt * 0.78
                )
                img[rs, cs] = img[rs, cs] * (1 - cov[..., None]) + fresh * cov[..., None]
                label[rs, cs][cov >= 0.5] = PATCH_LABEL
                continue
            cv_ = coverage(poly, s0, H, W)
            if cv_ is None:
                continue
            rs, cs, cov = cv_
            hard = cov >= 0.5
            if not hard.any():
                continue
            nh, nw = cov.shape
            drng = np.random.default_rng(d.seed)
            dist_in = cv2.distanceTransform(hard.astype(np.uint8), cv2.DIST_L2, 3) * RES
            sub = img[rs, cs]
            if d.kind == "depression":
                shade = (1 - 0.18 * np.clip(dist_in / 0.25, 0, 1)) * (
                    1.0 + 0.04 * value_noise(row0 + rs.start, nh, nw, 12, d.seed % 9973)
                )
                inner = sub * shade[..., None]
            else:
                depth = np.clip(dist_in / drng.uniform(0.06, 0.15), 0, 1)[..., None]
                gravel = (
                    0.75
                    + 0.35 * cv2.GaussianBlur(drng.random((nh, nw)).astype(np.float32), (0, 0), 1.2)
                    + 0.10 * value_noise(row0 + rs.start, nh, nw, 5, d.seed % 9973)
                )[..., None]
                rel = (rows_s[rs, None] - poly[:, 0].min()) / max(np.ptp(poly[:, 0]), 1e-3)
                wall = (1 + 0.25 * (np.clip(rel, 0, 1) - 0.5) * (1 - depth[..., 0]))[..., None]
                dark = drng.uniform(0.45, 0.65)
                tint = np.array([0.92, 0.97, 1.05], np.float32)
                inner = (sub * (1 - depth) * 0.85 + dark * gravel * asphalt * depth) * wall * tint
                if d.attrs.get("water"):  # standing water
                    water = depth[..., 0] > 0.4
                    inner[water] = np.array([0.30, 0.27, 0.24], np.float32) + 0.05 * gravel[water]
            img[rs, cs] = sub * (1 - cov[..., None]) + inner * cov[..., None]
            rim = cv2.dilate(hard.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~hard
            img[rs, cs][rim] *= 0.82
            label[rs, cs][hard] = CLASS_IDS[d.kind]
            inst[rs, cs][hard] = i + 1

        # --- per-pass shadows & wet patches ------------------------------------------------------
        for f in self._overlapping(w.pass_features.get(k, []), s0, s1):
            sig = 4 if f.kind == "shadow" else 8
            cv_ = coverage(f.data["poly"], s0, H, W, ss=2, margin_px=3 * sig)
            if cv_ is None:
                continue
            rs, cs, cov = cv_
            mf = cv2.GaussianBlur(cov, (0, 0), sig)[..., None]
            if f.kind == "shadow":
                img[rs, cs] *= (1 - f.data["strength"] * mf) * (1 + 0.05 * mf * np.array([0.2, 0.0, -0.2], np.float32))
            else:
                nh, nw = cov.shape
                sheen = (0.5 + 0.5 * value_noise(row0 + rs.start, nh, nw, 120, w.seed + 77))[..., None]
                img[rs, cs] = img[rs, cs] * (1 - 0.45 * mf) + mf * 0.10 * sheen * np.array([1.0, 0.95, 0.9], np.float32)

        np.clip(img, 0.0, 1.0, out=img)
        img8 = (img * 255.0).astype(np.uint8)
        return Tile(index, img8, label, inst)


def tile_index(s: float) -> int:
    return int(math.floor(s / TILE_M))
