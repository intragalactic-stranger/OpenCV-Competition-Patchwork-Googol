"""Frame triage: keep only the frames worth segmenting (stage [1] of the perception pipeline).

Travel per frame comes from *visual odometry on the road plane*: Shi-Tomasi corners inside the road ROI
are tracked with pyramidal Lucas-Kanade (forward-backward checked), both ends are projected onto the
ground with the calibrated camera, and the median forward displacement is the distance driven. This
needs no GNSS speed (1 Hz, metres of error) and is naturally zero at a signal stop.

Keep rule (spatial sampling, independent of frame rate):
  - keep the first sharp frame after every `spacing_m` (3 m) of travel, so each road point falls inside
    the 4-12 m measurement band of at least two kept frames (what multi-frame fusion needs);
  - additionally keep a frame where ROI edge energy spikes (candidate defect) if >= spacing_m/2 since the
    last kept frame;
  - frames below `blur_ratio` x the rolling median sharpness are deferred to the next sharp frame.
The proposal's "8-12% of 60 fps frames" target is restated as kept frames per km (decision D-23).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from patchwork.camera import CameraModel


@dataclass(frozen=True)
class TriageConfig:
    spacing_m: float = 3.0
    min_speed_kmh: float = 5.0
    blur_ratio: float = 0.5
    spike_z: float = 4.0
    scale: float = 0.25  # work on a 480x270 copy
    roi_y: tuple[float, float] = (4.0, 20.0)
    roi_x: float = 4.0
    max_corners: int = 200
    min_tracks: int = 12


@dataclass
class FrameScore:
    index: int
    travel_m: float  # forward motion since the previous frame (visual odometry)
    tracks: int
    sharpness: float  # Laplacian variance in the ROI
    edge: float  # mean Sobel magnitude in the ROI
    kept: bool = False
    reason: str = ""


@dataclass
class TriageResult:
    scores: list[FrameScore] = field(default_factory=list)

    @property
    def kept(self) -> list[int]:
        return [s.index for s in self.scores if s.kept]

    @property
    def keep_rate(self) -> float:
        return len(self.kept) / max(len(self.scores), 1)

    @property
    def distance_m(self) -> float:
        return float(sum(s.travel_m for s in self.scores))

    def summary(self) -> dict:
        reasons: dict[str, int] = {}
        for s in self.scores:
            if s.kept:
                reasons[s.reason] = reasons.get(s.reason, 0) + 1
        d = self.distance_m
        return {
            "frames": len(self.scores),
            "kept": len(self.kept),
            "keep_rate": round(self.keep_rate, 4),
            "distance_m": round(d, 1),
            "kept_per_km": round(1000 * len(self.kept) / d, 1) if d > 0 else None,
            "reasons": reasons,
        }


class Triage:
    """Streaming triage: call `push(frame)` for every decoded frame, in order."""

    def __init__(self, cam: CameraModel, fps: float, cfg: TriageConfig | None = None):
        self.cam, self.fps, self.cfg = cam, fps, cfg or TriageConfig()
        c = self.cfg
        self.size = (int(round(cam.width * c.scale)), int(round(cam.height * c.scale)))
        quad = np.array([[-c.roi_x, c.roi_y[0]], [c.roi_x, c.roi_y[0]], [c.roi_x, c.roi_y[1]], [-c.roi_x, c.roi_y[1]]])
        uv = cam.ground_to_pixel(quad, distort=True) * c.scale
        self.roi = np.zeros(self.size[::-1], np.uint8)
        cv2.fillConvexPoly(self.roi, np.round(uv).astype(np.int32), 255)
        self.roi_bool = self.roi > 0
        self.min_step = c.min_speed_kmh / 3.6 / fps
        self.prev: np.ndarray | None = None
        self.last_travel = 0.0
        self.since_kept = np.inf
        self.sharp_hist: deque[float] = deque(maxlen=45)
        self.edge_hist: deque[float] = deque(maxlen=45)
        self.result = TriageResult()

    def _travel(self, prev: np.ndarray, cur: np.ndarray) -> tuple[float, int]:
        c = self.cfg
        p0 = cv2.goodFeaturesToTrack(prev, c.max_corners, 0.01, 6, mask=self.roi)
        if p0 is None or len(p0) < c.min_tracks:
            return self.last_travel, 0
        lk = {"winSize": (21, 21), "maxLevel": 3}
        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, **lk)
        pb, st2, _ = cv2.calcOpticalFlowPyrLK(cur, prev, p1, None, **lk)
        ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((p0 - pb).reshape(-1, 2), axis=1) < 0.5)
        if ok.sum() < c.min_tracks:
            return self.last_travel, int(ok.sum())
        g0 = self.cam.pixel_to_ground(p0.reshape(-1, 2)[ok] / c.scale)
        g1 = self.cam.pixel_to_ground(p1.reshape(-1, 2)[ok] / c.scale)
        valid = (g0[:, 1] > 0) & (g1[:, 1] > 0)
        if valid.sum() < c.min_tracks:
            return self.last_travel, int(valid.sum())
        return float(np.median(g0[valid, 1] - g1[valid, 1])), int(valid.sum())

    def push(self, frame_bgr: np.ndarray) -> FrameScore:
        c = self.cfg
        small = cv2.resize(frame_bgr, self.size, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_32F)
        sharp = float(lap[self.roi_bool].var())
        gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
        edge = float(cv2.magnitude(gx, gy)[self.roi_bool].mean())

        if self.prev is None:
            travel, tracks = 0.0, 0
        else:
            travel, tracks = self._travel(self.prev, gray)
        if travel < self.min_step:  # stopped or crawling: no progress
            travel = 0.0
        self.last_travel = travel
        self.prev = gray

        s = FrameScore(len(self.result.scores), travel, tracks, sharp, edge)
        self.since_kept += travel
        med_sharp = float(np.median(self.sharp_hist)) if self.sharp_hist else sharp
        sharp_ok = sharp >= c.blur_ratio * med_sharp
        spike = False
        if len(self.edge_hist) >= 15:
            e = np.asarray(self.edge_hist)
            med = float(np.median(e))
            mad = float(np.median(np.abs(e - med))) * 1.4826 + 1e-6
            spike = (edge - med) / mad > c.spike_z
        if sharp_ok and travel > 0:
            if self.since_kept >= c.spacing_m:
                s.kept, s.reason = True, "spacing"
            elif spike and self.since_kept >= c.spacing_m / 2:
                s.kept, s.reason = True, "edge_spike"
        if s.kept:
            self.since_kept = 0.0
        self.sharp_hist.append(sharp)
        self.edge_hist.append(edge)
        self.result.scores.append(s)
        return s


def triage_video(path: str, cam: CameraModel, fps: float, cfg: TriageConfig | None = None) -> TriageResult:
    t = Triage(cam, fps, cfg)
    cap = cv2.VideoCapture(path)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t.push(frame)
    cap.release()
    return t.result
