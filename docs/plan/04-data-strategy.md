# 04: Data strategy: open data first, synthetic where needed

## 1. Principles

1. **Open data for appearance, synthetic for truth.** Real images teach the model what Indian potholes look like. Synthetic passes give exact area, position and repair status, which no open dataset has.
2. **Every byte has a licence noted** in `data/LICENSES.md` before it is used.
3. **Everything synthetic is seeded and reproducible**: `make synth SEED=… PASS=…` regenerates identical data.
4. **Privacy holds even for open data.** Every real image goes through the same face and plate blur before it is stored in our buckets.

## 2. Open datasets

| Dataset | What it has | Use | Licence (verify in Phase 1) |
|---|---|---|---|
| **Indian Roads** (IIT Bombay e-Yantra, 2021) | 3,227 images, **pixel-level instance masks**; classes include road, footpath, shallow pothole, other pothole; train 2,475 / val 752 | **Primary segmentation training + real validation (masks)**; source of real pothole cut-outs for compositing | ⚠️ confirm before use |
| **RDD2022** (sekilab), India subset | Vehicle-mounted smartphone images (960×720 → 720×720), **bounding boxes**; D40 = pothole | **External detection-generalisation check** (box-level recall/precision) | CC BY-SA 4.0 |
| **IndiaRDD2022** (Roboflow Universe) | Pothole annotations on India RDD images | Extra training/validation if export includes polygons | CC BY 4.0 |
| **OpenStreetMap** (Mumbai extract) | Road geometry, names, hierarchy; POIs: schools, hospitals, bus stops | Corridor geometry, road snapping fallback, `lookup_context` | ODbL 1.0 (attribution) |
| **Pretrained weights** | SegFormer `mit-b0` (ImageNet) or MobileNetV3 (torchvision) | Backbone initialisation | mit-b0: NVIDIA SegFormer licence (research/non-commercial) ⚠️; torchvision: BSD-3. See decision D-07. |
| **OpenCV Zoo** | YuNet face detector (ONNX) | Privacy blur | MIT |
| Licence-plate detector | Small open model (e.g. from OpenCV Zoo or a YOLO plate model with a permissive licence) | Privacy blur | verify |

Download scripts live in `scripts/data/` and write to `data/raw/<dataset>/` with a `SOURCE.md` (URL, date, checksum, licence).

## 3. The synthetic road generator (`src/patchwork/synth/`)

### 3.1 What it produces per pass
```
data/synth/<world_seed>/pass_<k>/
  clip_<n>.mp4          1920×1080, 30 fps (60 optional), H.264, lens distortion applied
  clip_<n>.gpx          GNSS 1 Hz with realistic noise (worse in "urban canyon" and tunnel segments)
  clip_<n>.imu.csv      100 Hz accel + gyro (speed changes, stops, bumps over defects)
  clip_<n>.meta.json    camera id, calibration id, pass id, start time, route segment ids
  truth/
    defects.json        every defect: world position, polygon in road-plane metres, exact area m², type, state this pass
    frames/<idx>.png    per-frame ground-truth masks (sampled frames only, to save disk)
    events.json         state transitions since the previous pass (repaired / degraded / new)
calib/charuco_<cam>/    rendered ChArUco views through the same camera (for calibration)
```

### 3.2 How a frame is rendered (physically consistent, so IPM is exact)

1. **World and route.** The corridor polyline comes from OSM (`synth/corridor.py`). A vehicle moves along it at a speed profile: 60–80 km/h on the Coastal Road, 20–45 km/h on arterials, with stops at signals. Position is arc length `s`.
2. **Road surface in metric space.** For the window `[s+2 m, s+40 m] × [-6 m, +6 m]` in the road frame, `synth/road.py` renders a ground texture at **1 cm/pixel**:
   - asphalt base: multi-octave noise + aggregate speckle + wear tone, seeded per road segment (stable across passes)
   - lane markings, tar seams and old patches (seeded, persistent)
   - **defects** (`synth/defects.py`): polygons in metres, shaded as depressions (darker core, rim highlight, inner gravel texture); appearance either **procedural** or **cut from real Indian Roads masks** and blended with `cv2.seamlessClone`
   - **distractors** (D4): shadows (trees, poles, vehicles), wet sheen / puddles, manhole covers, speed breakers, painted arrows
3. **Camera projection.** Known intrinsics K (fx ≈ 1,400 px, 1920×1080, about 69° HFOV), mounting height h ≈ 1.30 m, pitch ≈ 8° down, small roll. The road-plane → image homography is `H = K [r1 r2 t]`. `cv2.warpPerspective` maps the metric texture into the image. Sky, horizon and building band are filled procedurally. Optional distant vehicles add occlusion.
4. **Lens distortion.** Barrel distortion (k1 ≈ −0.28, k2 ≈ 0.08, small p1/p2) is applied with `cv2.remap`, so the calibration and undistortion stages have real work to do.
5. **Photometric realism.** Exposure jitter, vignetting, motion blur proportional to speed, JPEG/H.264 compression, optional rain streaks and night gain noise.
6. **Ground-truth masks** are produced by the same warp applied to the defect layer, so they match pixel for pixel.

Because the geometry is known exactly, ground-truth **area in m² is the polygon area**, with zero measurement error.

### 3.3 Defect lifecycle across passes (D3)

Each defect is an entity with a stable `truth_id`. Between pass *k* and *k+1*, a seeded Markov process chooses:

| Transition | Probability (default) | Rendering |
|---|---|---|
| unchanged | 0.60 | Same polygon, same texture (slight lighting change) |
| repaired | 0.20 | Polygon replaced by a darker, smoother **patch** texture with a crisp rectangular-ish edge |
| degraded | 0.15 | Polygon dilated by 10–40% plus new fragment edges |
| new | Poisson λ = 0.3 per km | New defect appears |
| (repaired → re-failed) | 0.05 | Patch edge breaks |

Expected counts for a 25 km corridor with about 12 defects/km on arterials: roughly 250 defects in pass 1 and about 50 repairs per transition. That is far above the proposal's "≥ 15 repairs" floor.

### 3.4 GNSS and IMU realism
- GNSS: a random-walk bias (σ 2 m, τ 60 s) + white noise (σ 1.5 m), ×2.5 in "urban canyon" segments (tall buildings from OSM building heights where available, otherwise tagged manually). Outage in the Coastal Road tunnel (tunnel segments are excluded from the register, as in the proposal).
- IMU: speed profile derivative + gravity + noise; bumps when wheels cross defects (lets triage use the IMU as in the proposal).

### 3.5 Scale and compute budget
- 25 km at an average of 40 km/h ≈ 37 min ≈ 67k frames at 30 fps. Rendering is about 15–25 ms/frame on 4 vCPU → **about 20–30 min per pass** locally. Passes can also be rendered as parallel Batch array jobs.
- For quick iteration: `--segment worli-seaface` renders a 2–3 km sub-route in under 3 minutes.

## 4. Evaluation datasets (proposal D1–D4)

| Set | Proposal | Our version | Size |
|---|---|---|---|
| **D1** measured set | 300 tape-measured potholes | 300 synthetic defects on the arterials with exact area; plus Indian Roads val (752 real images) for mask quality | 300 defects + 752 images |
| **D2** control section | Coastal Road spine, every pass | Synthetic Coastal Road segments: clean surface + realistic seams/markings/shadows, **zero defects** | about 10 km per pass |
| **D3** repeat passes | 8–9 weekly passes | 3 passes at midpoint → 8 passes by the end, lifecycle as in §3.3 | about 250 tracks, about 50 repairs per step |
| **D4** false-positive zoo | about 60 monsoon clips | 60 short synthetic clips, each dominated by one distractor class (wet, night, seams, manholes, shadows, markings, speed breakers) | 60 clips |
| External | RDD2022 | RDD2022-India (boxes) | test split |

## 5. Training data mix (segmentation)

| Source | Share | Why |
|---|---|---|
| Indian Roads train (real masks) | about 50% | Real appearance, real Indian roads |
| Synthetic frames (perspective view) | about 35% | Same camera geometry as inference |
| Synthetic + real composites (real pothole cut-outs on synthetic roads) | about 15% | Bridge the domain gap |

Classes: `background`, `pothole`, `edge_break`, `depression`. Indian Roads' "shallow" and "other pothole" map onto these, and the mapping is recorded in `training/class_map.yaml`.

Validation always reports **real (Indian Roads val)** and **synthetic (D1)** separately, so the synthetic domain cannot hide a real-world weakness.

## 6. Storage layout

```
s3://patchwork-<acct>-raw/            blurred clips + sidecars (30-day lifecycle expiry)
s3://patchwork-<acct>-artifacts/
   models/<model_version>/model.onnx, metrics.json, class_map.yaml
   calib/<calibration_id>.json
   crops/<defect_obs_id>.jpg            rectified + perspective crops
   overlays/<defect_obs_id>.png
   traces/<agent_run_id>.json
   workorders/<package_id>.pdf
   reports/                             evaluation outputs used by docs/midpoint
s3://patchwork-<acct>-datasets/       open datasets mirrored for SageMaker (Intelligent-Tiering)
```
