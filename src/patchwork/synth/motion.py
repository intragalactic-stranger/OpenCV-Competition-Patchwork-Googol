"""Vehicle motion for one pass: speed profile, stops, lane wander, camera jitter, GNSS and IMU.

All series are seeded by (world seed, pass). True poses are exact; GNSS/IMU are the noisy sensors
perception must cope with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from patchwork.synth.corridor import TO_WGS, Corridor
from patchwork.synth.world import World

G = 9.81


@dataclass
class Trajectory:
    t: np.ndarray  # frame times (s)
    s: np.ndarray  # chainage (m)
    speed: np.ndarray  # m/s
    lateral: np.ndarray  # m, + right of the driving line
    pitch: np.ndarray  # deg (absolute camera pitch)
    roll: np.ndarray
    yaw: np.ndarray
    exposure: np.ndarray
    fps: float


def _ou(rng: np.random.Generator, n: int, dt: float, sigma: float, tau: float) -> np.ndarray:
    """Ornstein-Uhlenbeck process (stationary std `sigma`, correlation time `tau`)."""
    x = np.zeros(n)
    a = math.exp(-dt / tau)
    b = sigma * math.sqrt(1 - a * a)
    eps = rng.normal(size=n)
    for i in range(1, n):
        x[i] = a * x[i - 1] + b * eps[i]
    return x


def speed_limits(world: World, s_grid: np.ndarray) -> np.ndarray:
    return np.array([world.profile_at(min(s, world.corridor.length_m - 1e-3)).speed_kmh / 3.6 for s in s_grid])


def simulate(
    world: World,
    pass_k: int,
    fps: float = 15.0,
    s_start: float = 0.0,
    s_end: float | None = None,
    base_pitch: float = 8.0,
) -> Trajectory:
    rng = np.random.default_rng([world.seed, pass_k, 11])
    c = world.corridor
    s_end = c.length_m if s_end is None else min(s_end, c.length_m)
    # target speed on a 1 m grid, with signal stops on arterials
    grid = np.arange(s_start, s_end + 1.0, 1.0)
    v_target = speed_limits(world, grid) * rng.uniform(0.85, 1.05)
    stops: list[tuple[float, float]] = []
    for s in np.arange(s_start + 150, s_end - 50, 600.0):
        prof = world.profile_at(s)
        if prof.key in ("primary", "secondary") and rng.random() < 0.35:
            stops.append((float(s + rng.uniform(-200, 200)), float(rng.uniform(4, 20))))
    dt = 1.0 / fps
    t_list, s_list, v_list = [0.0], [s_start], [0.0]
    s, v, t = s_start, 0.0, 0.0
    stop_iter = iter(sorted(stops))
    next_stop = next(stop_iter, None)
    wait = 0.0
    a_max, d_max = 1.5, 2.5
    while s < s_end:
        if wait > 0:
            wait -= dt
            v = 0.0
        else:
            vt = float(np.interp(s, grid, v_target))
            if next_stop is not None:
                dist = next_stop[0] - s
                if dist <= 0.5:
                    wait, next_stop = next_stop[1], next(stop_iter, None)
                    v = 0.0
                else:
                    vt = min(vt, math.sqrt(2 * d_max * 0.8 * dist))
            v = min(v + a_max * dt, vt) if vt > v else max(v - d_max * dt, vt)
        s += v * dt
        t += dt
        t_list.append(t)
        s_list.append(min(s, s_end))
        v_list.append(v)
    n = len(t_list)
    s_arr = np.array(s_list)
    lateral = rng.normal(0, 0.15) + _ou(rng, n, dt, 0.22, 8.0)
    ds = np.gradient(s_arr).clip(1e-3, None)
    yaw = np.degrees(np.arctan2(np.gradient(lateral), ds)) * (np.array(v_list) > 0.5) + _ou(rng, n, dt, 0.15, 2.0)
    pitch = base_pitch + _ou(rng, n, dt, 0.10, 1.5)
    # bumps: brief pitch excursions when the wheels cross a pothole / speed breaker in the vehicle's path
    bump_s = [
        float(d.poly_at(pass_k)[:, 0].mean())
        for d in world.defects
        if d.states.get(pass_k) in ("present", "degraded") and abs(float(d.poly_at(pass_k)[:, 1].mean())) < 1.2
    ]
    bump_s += [f.data["s"] for f in world.features if f.kind == "breaker"]
    for bs in bump_s:
        if s_start <= bs <= s_end:
            i = int(np.searchsorted(s_arr, bs))
            span = np.arange(max(i - 2, 0), min(i + 6, n))
            pitch[span] += 0.6 * np.exp(-(((span - i) / 2.0) ** 2)) * np.sign(rng.normal())
    roll = _ou(rng, n, dt, 0.15, 3.0)
    exposure = 1.0 + _ou(rng, n, dt, 0.06, 20.0)
    return Trajectory(np.array(t_list), s_arr, np.array(v_list), lateral, pitch, roll, yaw, exposure, fps)


def true_positions(c: Corridor, s: np.ndarray, lateral: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """UTM x, y and heading (rad) of the camera for chainage + lateral offset."""
    xs, ys, hs = np.empty(len(s)), np.empty(len(s)), np.empty(len(s))
    for i, (si, li) in enumerate(zip(s, lateral, strict=True)):
        x, y, h = c.pose_at(float(si))
        # + lateral = right of travel direction: rotate heading by -90 deg
        xs[i] = x + li * math.sin(h)
        ys[i] = y - li * math.cos(h)
        hs[i] = h
    return xs, ys, hs


def road_to_utm(c: Corridor, s: float, d: float) -> tuple[float, float]:
    x, y, h = c.pose_at(s)
    return x + d * math.sin(h), y - d * math.cos(h)


def road_to_wgs(c: Corridor, s: float, d: float) -> tuple[float, float]:
    x, y = road_to_utm(c, s, d)
    lon, lat = TO_WGS.transform(x, y)
    return float(lat), float(lon)


def gnss(world: World, traj: Trajectory, pass_k: int, rate_hz: float = 1.0) -> dict[str, np.ndarray]:
    """1 Hz GNSS fixes: random-walk bias + white noise; x2.5 on arterials (urban canyon); no fix in tunnels."""
    rng = np.random.default_rng([world.seed, pass_k, 23])
    c = world.corridor
    t = np.arange(0.0, traj.t[-1], 1.0 / rate_hz)
    s = np.interp(t, traj.t, traj.s)
    lat_off = np.interp(t, traj.t, traj.lateral)
    x, y, _ = true_positions(c, s, lat_off)
    n = len(t)
    bias = np.stack([_ou(rng, n, 1 / rate_hz, 2.0, 60.0), _ou(rng, n, 1 / rate_hz, 2.0, 60.0)], 1)
    white = rng.normal(0, 1.5, (n, 2))
    factor = np.array(
        [
            1.0 if world.profile_at(si).key in ("control",) else 2.5 if world.profile_at(si).key != "tunnel" else 0
            for si in s
        ]
    )
    tunnel = np.array([world.profile_at(si).key == "tunnel" for si in s])
    ex = (bias[:, 0] + white[:, 0]) * np.maximum(factor, 1)
    ey = (bias[:, 1] + white[:, 1]) * np.maximum(factor, 1)
    lon, lat = TO_WGS.transform(x + ex, y + ey)
    lat, lon = np.asarray(lat), np.asarray(lon)
    lat[tunnel] = np.nan
    lon[tunnel] = np.nan
    hdop = np.where(tunnel, np.nan, 0.8 * np.maximum(factor, 1))
    return {"t": t, "lat": lat, "lon": lon, "hdop": hdop, "fix": (~tunnel).astype(int)}


def imu(traj: Trajectory, world: World, pass_k: int, rate_hz: float = 100.0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng([world.seed, pass_k, 31])
    t = np.arange(0.0, traj.t[-1], 1.0 / rate_hz)
    v = np.interp(t, traj.t, traj.speed)
    ax = np.gradient(v, t) + rng.normal(0, 0.05, len(t))
    s = np.interp(t, traj.t, traj.s)
    c = world.corridor
    heading = np.unwrap(np.array([c.pose_at(float(si))[2] for si in s[:: int(rate_hz // 10) or 1]]))
    heading = np.interp(t, t[:: int(rate_hz // 10) or 1], heading)
    gz = np.gradient(heading, t) + rng.normal(0, 0.002, len(t))
    ay = v * gz + rng.normal(0, 0.05, len(t))
    pitch_rate = np.gradient(np.radians(np.interp(t, traj.t, traj.pitch)), t)
    az = G + 2.0 * pitch_rate * v.clip(0, None) / 10 + rng.normal(0, 0.08, len(t))
    return {"t": t, "ax": ax, "ay": ay, "az": az, "gx": np.zeros_like(t), "gy": pitch_rate, "gz": gz}
