# 06: Perception pipeline (OpenCV 5)

OpenCV 5 is the runtime for the **whole** perception stack. Each stage is a pure function in `src/patchwork/perception/`, unit-tested in isolation. `pipeline/runner.py` chains them.

```
clip.mp4 + gpx + imu
  │
  ├─[1] triage.py      ─ keep 8–12% of frames
  ├─[2] privacy.py     ─ YuNet faces + plate detector → blur burned in
  ├─[3] calib.py       ─ load calibration_id (or compute from ChArUco) → undistort maps
  ├─[4] ipm.py         ─ road-plane homography → bird's-eye view (BEV) at 1 cm/px
  ├─[5] segment.py     ─ ONNX model in cv2.dnn ENGINE_NEW → class masks (perspective view)
  ├─[6] measure.py     ─ masks → BEV → contours → area m², L×W, uncertainty
  ├─[7] severity.py    ─ band + confidence; material estimate
  ├─[8] localise.py    ─ pixel → road-plane metres → vehicle pose (GNSS+IMU) → lat/lon, chainage
  ├─[9] track.py       ─ merge same defect across consecutive frames → one observation
  └─[10] register_match.py (Phase 6) ─ cross-pass registration → status
```

## [1] Frame triage (`triage.py`)
- Road ROI = the lower ~45% of the undistorted frame, trapezoid-masked. Downscale to **320×180**.
- Scores: Laplacian variance (sharpness), Sobel edge energy inside the ROI, and **sparse optical flow** (`cv2.calcOpticalFlowPyrLK` on `goodFeaturesToTrack`) giving median flow magnitude.
- IMU / GNSS speed < 5 km/h → drop (stopped or crawling).
- **Spatial sampling**: keep one frame per ~4 m of travel (so every road point appears in about 2–3 kept frames within the 3–15 m metric zone). Add extra frames where edge energy spikes (candidate defects).
- Output: list of kept frame indices with reasons. Target keep rate 8–12%, which is logged.

## [2] Privacy (`privacy.py`)
- **YuNet** (`cv2.FaceDetectorYN`, OpenCV Zoo ONNX) at 640 px, threshold 0.6 → Gaussian blur with a 20% margin.
- **Plates**: a small ONNX plate detector through `cv2.dnn`; fallback heuristic (MSER/contour rectangles with plate aspect ratio inside detected vehicle regions).
- Runs **before** any frame is written. The output carries `privacy_blurred=True`. Unit test: inject a synthetic face/plate and assert blur variance drops.

## [3] Calibration and undistortion (`calib.py`)
- `cv2.aruco.CharucoBoard` (7×5 squares, DICT_5X5_100) + `cv2.aruco.CharucoDetector` → `cv2.calibrateCamera` (OpenCV 5 reorganised 3D module). Reprojection error must be < 0.5 px, otherwise the calibration is rejected.
- Output `calib/<calibration_id>.json`: K, dist, image size, RMS, created_at.
- `cv2.initUndistortRectifyMap` computed once per clip, then `cv2.remap` per frame.
- For synthetic data, ChArUco views are **rendered** through the synthetic camera (with distortion), so we exercise the real path and can compare the estimated K and dist with the truth.

## [4] Inverse perspective mapping (`ipm.py`)
- Extrinsics: mounting height *h*, pitch θ, roll φ (from `meta.json`, refined).
- Road plane Z=0 in a vehicle frame (X right, Y forward). Homography image ← plane: `H = K · [r1 r2 t]`. BEV warp = `H⁻¹` composed with a scaling to **1 cm/px**.
- Metric ROI: Y ∈ [3 m, 15 m], X ∈ [−5 m, +5 m] → BEV 1000×1200 px. Beyond 15 m the pixel footprint grows too large, so area uncertainty rises and those pixels are excluded from measurement.
- **Self-check (lane width)**: detect lane markings in the BEV (top-hat + Hough lines). Measured lane width must be within ±10% of the nominal 3.5 m (or a per-road OSM value). Otherwise flag the calibration as stale (`measurement_status = detected_not_measured`).
- Pitch refinement: a small search over θ ±1.5° that makes BEV lane lines parallel (vanishing-point consistency), so changes from vehicle loading don't bias area.

## [5] Segmentation (`segment.py`)
- Model: SegFormer-B0-class (Phase 3), input normalised RGB, dynamic H×W (multiple of 32). Exported ONNX opset 17.
- Runtime:
  ```python
  net = cv2.dnn.readNetFromONNX(path, cv2.dnn.ENGINE_NEW)   # confirmed in Phase 0 (OpenCV 5.0.0)
  blob = cv2.dnn.blobFromImage(img, scalefactor=1/255, size=(W,H), mean=…, swapRB=True)
  net.setInput(blob); logits = net.forward()   # (1, C, H/4, W/4)
  ```
- Upsample logits → softmax → per-class masks; morphology open/close; drop blobs < 50 BEV-equivalent cm².
- Inference runs on the **perspective** frame (where the model was trained) at 960×544 (dynamic shapes allow 1920×1088 for small far defects). Masks are then warped to the BEV.
- **Parity test** (`training/parity.py`): OpenCV `ENGINE_NEW` vs onnxruntime on 50 images, max |Δlogit| ≤ 1e-3. Also run `ENGINE_CLASSIC` to document that 4.x-style loading fails or differs (proposal claim).
- Fallback: if an operator is unsupported in `ENGINE_NEW`, use `ENGINE_ORT` (OpenCV 5's onnxruntime-backed engine), then `ENGINE_CLASSIC`, and record the deviation in decision D-08. The pipeline never blocks on this.

## [6] Measurement (`measure.py`)
- Warp each class mask into the BEV with nearest-neighbour interpolation. `cv2.findContours` → polygons.
- `area_m2 = countNonZero(mask_bev) × (0.01 m)²`.
- `length_m`, `width_m` from `cv2.minAreaRect`.
- **Uncertainty**: per-defect, from (a) the pixel footprint at its range (the ground sampling distance grows with Y), × a one-pixel boundary band of the perspective mask projected to the BEV, plus (b) the pitch uncertainty propagated (±0.3°). Reported as ±m².
- **Multi-frame fusion**: the same defect is seen in 2–4 kept frames. Area = the median of frames where the defect lies in Y ∈ [4 m, 12 m] (the best-resolved zone).

## [7] Severity and material (`severity.py`)
- v1: the rules in [05 §6](05-defect-record-schema.md#6-severity-and-material-defaults-v1-calibrated-in-phase-3).
- v2 (Phase 3+): a small logistic model on [area, elongation, mask confidence, darkness contrast, wheel_path], calibrated (isotonic) against synthetic severity labels.
- Material: area × thickness × density × (1 + wastage). Assumptions are printed.

## [8] Localisation (`localise.py`)
- Vehicle pose per frame: GNSS (1 Hz) smoothed by a constant-velocity Kalman filter with IMU yaw rate, then **map-matched** to the corridor polyline. Heading comes from the road tangent.
- Defect ground position = vehicle pose ⊕ (X, Y) of the defect centroid in the vehicle frame → UTM 43N → WGS84.
- Chainage = projection onto the snapped road segment (PostGIS `ST_LineLocatePoint` or Amazon Location SnapToRoads).
- Target: median error ≤ 8 m (measured exactly against synthetic truth).

## [9] Within-pass tracking (`track.py`)
- Consecutive kept frames: predict the defect's BEV position from vehicle motion (Δchainage), associate by IoU in road coordinates (Hungarian), and merge into one **observation**.

## [10] Cross-pass registration (`register_match.py`, Phase 6; basic version at midpoint if time allows)
1. **GNSS gate**: candidates = defects within 15 m and the same road segment ±10 m chainage.
2. **Visual confirm**: ORB (`cv2.ORB_create(2000)`) on the rectified BEV patches (2 m × 2 m around each), BF Hamming + ratio test → `cv2.findHomography(RANSAC)`. Accept if inliers ≥ 25 and the homography is near-rigid (scale 0.9–1.1, small shear). This uses the stable texture around the defect (asphalt, seams) and does not rely on the defect itself, which may have changed.
3. **Compare** the aligned masks: IoU and area delta.
   - IoU ≥ 0.5 and |Δarea| < 15% → **unchanged**
   - mask mostly gone and patch texture detected (lower variance, edge-bounded region) → **repaired**
   - area +15% or more → **degraded**
   - no prior match → **new**
   - water or specular → **obscured** (re-queue)
4. Write a `status_event` with evidence (before and after crops) for the agent and the console.

## Failure modes and behaviour

| Failure | Behaviour |
|---|---|
| Calibration missing or stale (lane-width check fails) | Detect but don't measure: `detected_not_measured`, excluded from work orders |
| Model unsupported in `ENGINE_NEW` | Fall back (§5), log the deviation, metric `engine_fallback=1` |
| GNSS outage (tunnel) | Segment excluded from the register; dead-reckoning only for continuity |
| Standing water | `obscured`, re-inspect next pass |
| Spot interruption mid-clip | Batch retry; idempotency key prevents duplicates; per-stage checkpoints in S3 |

## Performance budget (Graviton c7g.xlarge, 4 vCPU)

| Stage | Per kept frame | Notes |
|---|---|---|
| Undistort + IPM | ~6 ms | Precomputed maps |
| Segmentation 960×544 | ~120–200 ms | ENGINE_NEW, CPU, KleidiCV/HAL |
| Measure + localise | ~5 ms | |
| **Per km** (about 250 kept frames) | **~40–60 s CPU** | → 25 km in about 20 min on one instance, or parallel per clip |
