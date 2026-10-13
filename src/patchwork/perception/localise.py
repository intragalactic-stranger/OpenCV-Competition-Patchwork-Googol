"""Localisation: where was the camera at every frame, and where is each defect (stage [8]).

The survey route is known (the corridor: an OSM polyline), so position is one number, the chainage s.
  - motion model: visual odometry from triage (metres per frame, ~1.5 % scale error, exact zero at stops)
  - measurements: 1 Hz GNSS fixes map-matched onto the corridor (windowed projection, so the loop's
    parallel carriageways cannot capture the fix); no fixes in the tunnel, odometry carries through
  - estimator: Kalman filter on [s, k, b] (k = odometry scale error, b = GNSS along-track bias as an
    Ornstein-Uhlenbeck process) + Rauch-Tung-Striebel smoother, since processing is offline.
A defect seen at road-plane (X, Y) from frame f sits at chainage s_f + Y and lateral offset d_f + X.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyproj import Transformer

from patchwork.synth.corridor import Corridor

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
# consumer GNSS error per unit HDOP, split into a slowly varying bias (multipath, atmosphere; correlated over
# about a minute) and white noise. Treating the bias as white makes the filter overconfident.
BIAS_PER_HDOP = 2.5
WHITE_PER_HDOP = 1.9


class CorridorMatcher:
    def __init__(self, c: Corridor):
        self.c = c
        self.ax, self.ay = c.x[:-1], c.y[:-1]
        self.dx, self.dy = np.diff(c.x), np.diff(c.y)
        self.len2 = np.maximum(self.dx**2 + self.dy**2, 1e-9)

    def project(self, x: float, y: float, s_lo: float = -np.inf, s_hi: float = np.inf) -> tuple[float, float, float]:
        """Nearest corridor point to UTM (x, y) with chainage in [s_lo, s_hi] -> (s, d, distance)."""
        i0 = max(int(np.searchsorted(self.c.s, s_lo, side="right")) - 1, 0)
        i1 = min(int(np.searchsorted(self.c.s, s_hi, side="left")) + 1, len(self.ax))
        sl = slice(i0, i1)
        t = np.clip(((x - self.ax[sl]) * self.dx[sl] + (y - self.ay[sl]) * self.dy[sl]) / self.len2[sl], 0, 1)
        px, py = self.ax[sl] + t * self.dx[sl], self.ay[sl] + t * self.dy[sl]
        d2 = (x - px) ** 2 + (y - py) ** 2
        j = int(np.argmin(d2))
        seg_len = np.sqrt(self.len2[sl][j])
        s = float(self.c.s[i0 + j] + t[j] * seg_len)
        # signed lateral offset: + right of travel direction
        cross = self.dx[sl][j] * (y - self.ay[sl][j]) - self.dy[sl][j] * (x - self.ax[sl][j])
        return s, float(-cross / seg_len), float(np.sqrt(d2[j]))

    def initial_chainage(self, xs: np.ndarray, ys: np.ndarray) -> float:
        """Global match for the first fix, disambiguated by the direction of travel over the first fixes."""
        cand = []
        t = np.clip(((xs[0] - self.ax) * self.dx + (ys[0] - self.ay) * self.dy) / self.len2, 0, 1)
        d = np.hypot(xs[0] - (self.ax + t * self.dx), ys[0] - (self.ay + t * self.dy))
        heading = np.arctan2(ys[-1] - ys[0], xs[-1] - xs[0]) if np.hypot(xs[-1] - xs[0], ys[-1] - ys[0]) > 20 else None
        seg_heading = np.arctan2(self.dy, self.dx)
        for j in np.argsort(d)[:50]:
            if d[j] > 60:
                break
            ok = heading is None or np.cos(seg_heading[j] - heading) > 0.5
            cand.append((d[j] + (0 if ok else 1e3), float(self.c.s[j] + t[j] * np.sqrt(self.len2[j]))))
        if not cand:
            j = int(np.argmin(d))
            return float(self.c.s[j] + t[j] * np.sqrt(self.len2[j]))
        return min(cand)[1]


@dataclass
class Track:
    t: np.ndarray  # frame times (s)
    s: np.ndarray  # smoothed chainage per frame (m)
    sigma: np.ndarray  # 1-sigma chainage uncertainty (m)
    d: np.ndarray  # lateral offset (m, + right), 0 = on the mapped centreline
    scale: float  # estimated odometry scale correction (1 + k)
    gnss_used: int

    def latlon(self, c: Corridor, i: int, X: float = 0.0, Y: float = 0.0) -> tuple[float, float, float, float]:
        """WGS84 of a road-plane point (X right, Y forward) seen from frame i -> (lat, lon, s, d)."""
        s = float(self.s[i] + Y)
        d = float(self.d[i] + X)
        x, y, h = c.pose_at(s)
        lon, lat = TO_WGS.transform(x + d * np.sin(h), y - d * np.cos(h))
        return float(lat), float(lon), s, d


def localise(
    c: Corridor,
    frame_t: np.ndarray,
    odo_m: np.ndarray,
    gnss_t: np.ndarray,
    gnss_lat: np.ndarray,
    gnss_lon: np.ndarray,
    gnss_hdop: np.ndarray,
    window_m: float = 150.0,
    q_s: float = 0.05,
    q_k: float = 1e-5,
    bias_tau_s: float = 60.0,
) -> Track:
    """Kalman filter + RTS smoother on chainage. odo_m[i] = forward travel from frame i-1 to i."""
    matcher = CorridorMatcher(c)
    ok = np.isfinite(gnss_lat) & np.isfinite(gnss_lon)
    gx, gy = TO_UTM.transform(np.where(ok, gnss_lon, 0), np.where(ok, gnss_lat, 0))
    gx, gy = np.asarray(gx), np.asarray(gy)
    first = np.flatnonzero(ok)
    if len(first) == 0:
        raise ValueError("no GNSS fix in clip: cannot anchor the track")
    f0 = first[: min(len(first), 15)]
    s0 = matcher.initial_chainage(gx[f0], gy[f0])
    # cumulative odometry back to t=0 from the first fix time
    cum = np.cumsum(odo_m)
    t_first = gnss_t[first[0]]
    s_init = s0 - float(np.interp(t_first, frame_t, cum))

    n = len(frame_t)
    meas_at = np.searchsorted(frame_t, gnss_t)  # GNSS fix j is applied at frame meas_at[j]
    # state [s, k, b]: chainage, odometry scale error, GNSS along-track bias (Ornstein-Uhlenbeck, tau)
    x = np.array([s_init, 0.0, 0.0])
    sig_b = BIAS_PER_HDOP * float(np.nanmedian(gnss_hdop[ok]))
    P = np.diag([30.0**2, 0.03**2, sig_b**2])
    H = np.array([1.0, 0.0, 1.0])
    xs_f, Ps_f = np.zeros((n, 3)), np.zeros((n, 3, 3))
    xs_p, Ps_p, Fs = np.zeros((n, 3)), np.zeros((n, 3, 3)), []
    used = gi = 0
    for i in range(n):
        u = float(odo_m[i]) if i > 0 else 0.0
        dt = float(frame_t[i] - frame_t[i - 1]) if i > 0 else 0.0
        a = float(np.exp(-dt / bias_tau_s))
        F = np.array([[1.0, u, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, a]])
        x = np.array([x[0] + u * (1 + x[1]), x[1], a * x[2]])
        Q = np.diag([(q_s * max(u, 0.0)) ** 2 + 1e-6, q_k * max(u, 0.0) + 1e-12, sig_b**2 * (1 - a * a) + 1e-9])
        P = F @ P @ F.T + Q
        xs_p[i], Ps_p[i] = x, P
        Fs.append(F)
        while gi < len(gnss_t) and meas_at[gi] <= i:
            if ok[gi] and np.isfinite(gnss_hdop[gi]):
                s_meas, _, dist = matcher.project(gx[gi], gy[gi], x[0] - window_m, x[0] + window_m)
                sig_b = BIAS_PER_HDOP * float(gnss_hdop[gi])
                r = (WHITE_PER_HDOP * float(gnss_hdop[gi])) ** 2
                innov = s_meas - H @ x
                S = H @ P @ H + r
                if dist < 40 and innov**2 < 25 * S:  # gate: off-route fixes and outliers
                    K = P @ H / S
                    x = x + K * innov
                    P = (np.eye(3) - np.outer(K, H)) @ P
                    used += 1
            gi += 1
        xs_f[i], Ps_f[i] = x, P
    # Rauch-Tung-Striebel smoother
    xs, Ps = xs_f.copy(), Ps_f.copy()
    for i in range(n - 2, -1, -1):
        C = Ps_f[i] @ Fs[i + 1].T @ np.linalg.inv(Ps_p[i + 1])
        xs[i] = xs_f[i] + C @ (xs[i + 1] - xs_p[i + 1])
        Ps[i] = Ps_f[i] + C @ (Ps[i + 1] - Ps_p[i + 1]) @ C.T
    return Track(
        t=frame_t,
        s=xs[:, 0],
        sigma=np.sqrt(np.maximum(Ps[:, 0, 0], 0)),
        d=np.zeros(n),
        scale=float(1 + xs[-1, 1]),
        gnss_used=used,
    )
