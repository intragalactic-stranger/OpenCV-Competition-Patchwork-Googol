# Phase 2: Perception geometry

**Goal:** prove the geometry (calibration → undistortion → IPM → square metres) is right, **independent of any neural network**, using ground-truth (oracle) masks.
**Midpoint track:** yes.

## Checklist
- [x] `calib.py`: ChArUco detection + `calibrateCamera`; RMS < 0.5 px; recovered K/dist vs synthetic truth (fx within 1%). RMS 0.164 px, fx within 0.02%
- [x] Undistortion folded into the IPM remap (one `cv2.remap` from the distorted frame straight to the BEV)
- [x] `ipm.py`: homography from h/θ/φ; BEV at 1 cm/px over Y 3–15 m, X ±5 m
- [x] Pitch refinement from lane-line geometry (`pose.py`, pitch MAE 0.048°) · [ ] lane-width self-check (not yet)
- [x] `triage.py`: Laplacian sharpness, edge energy, LK flow projected to the road plane (visual odometry), stop gate, one frame per 3 m. 297 frames/km, 0% recall loss (D-23)
- [x] `privacy.py`: YuNet + character-row plate/text detector; `BlurredFrame` type; 4/4 injected plates; 0 of 112 pothole boxes blurred on RDD-India
- [x] `measure.py`: BEV mask → area, L×W, uncertainty; multi-frame median fusion; edge/bonnet truncation rejected
- [x] `localise.py`: KF [chainage, odometry scale, GNSS bias] + RTS smoother, windowed map-matching to the corridor. 3.9 m median vs 9.1 m raw GNSS
- [x] Within-pass merge: done inside `measure.py` (multi-frame fusion per defect) and the `assemble` step, no separate `track.py`. Known gap: one defect can still split into two blobs (second half)
- [x] Oracle-mask path: `python -m eval.metrics.area --oracle` (true masks → our geometry → m²). Model path: `pipeline/runner.py perceive|assemble` → observations + overlays (local)
- [x] Visuals for the midpoint pack: perspective vs BEV side-by-side with measured polygons; calibration board detection

## Exit criteria
| Check | Target | Command |
|---|---|---|
| Oracle-mask area MAPE | ≤ 5% | `python -m eval.metrics.area --oracle` |
| Localisation median error | ≤ 8 m (expected ≈ 2–4 m) | `python -m eval.metrics.localisation` |
| Triage keep rate | 8–12% with ≤ 2% recall loss | `python -m eval.metrics.triage_eval` |
| Calibration RMS | < 0.5 px | `pytest tests/perception/test_calib.py` |
| Privacy | 100% of injected faces/plates blurred | `pytest tests/perception/test_privacy.py` |
