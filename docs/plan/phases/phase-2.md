# Phase 2: Perception geometry

**Goal:** prove the geometry (calibration → undistortion → IPM → square metres) is right, **independent of any neural network**, using ground-truth (oracle) masks.
**Midpoint track:** yes.

## Checklist
- [ ] `calib.py`: ChArUco detection + `calibrateCamera`; RMS < 0.5 px; recovered K/dist vs synthetic truth (fx within 1%)
- [ ] Undistort maps cached per calibration
- [ ] `ipm.py`: homography from h/θ/φ; BEV at 1 cm/px over Y 3–15 m, X ±5 m
- [ ] Lane-width self-check + pitch refinement
- [ ] `triage.py`: variance, edge energy, LK optical flow, IMU speed gate, one frame per ~4 m; keep 8–12%
- [ ] `privacy.py`: YuNet + plate detector; blur-before-write enforced by the type (`BlurredFrame`)
- [ ] `measure.py`: BEV mask → area, L×W, uncertainty; multi-frame median fusion
- [ ] `localise.py`: Kalman-smoothed pose, map-matching, defect lat/lon + chainage
- [ ] `track.py`: within-pass merge
- [ ] `pipeline/runner.py --oracle-masks`: clip → observations.parquet + overlays (local)
- [ ] Visuals for the midpoint pack: perspective vs BEV side-by-side with measured polygons; calibration board detection

## Exit criteria
| Check | Target | Command |
|---|---|---|
| Oracle-mask area MAPE | ≤ 5% | `python -m eval.metrics.area --oracle` |
| Localisation median error | ≤ 8 m (expected ≈ 2–4 m) | `python -m eval.metrics.localisation` |
| Triage keep rate | 8–12% with ≤ 2% recall loss | `python -m eval.metrics.triage_eval` |
| Calibration RMS | < 0.5 px | `pytest tests/perception/test_calib.py` |
| Privacy | 100% of injected faces/plates blurred | `pytest tests/perception/test_privacy.py` |
