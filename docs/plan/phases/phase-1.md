# Phase 1: Data and synthetic world

**Goal:** a reproducible synthetic Mumbai corridor with exact ground truth, plus open datasets mirrored and licensed. **Freeze the defect schema.**
**Midpoint track:** yes.

## Checklist

### Open data (`scripts/data/`)
- [ ] Indian Roads dataset → `data/raw/indian_roads/` + `SOURCE.md` (URL, checksum, **licence confirmed**)
- [ ] RDD2022 India subset → `data/raw/rdd2022_india/` (CC BY-SA 4.0)
- [ ] Optional: IndiaRDD2022 (Roboflow, CC BY 4.0) if a polygon export exists
- [ ] Class-map to `pothole / edge_break / depression` → `training/class_map.yaml`
- [ ] Blur pass over real images (faces/plates) before upload to `s3://…-datasets/`
- [ ] `data/LICENSES.md`

### Corridor (`synth/corridor.py`)
- [ ] Overpass query for the named roads (Coastal Road, Worli Seaface / Khan Abdul Gaffar Khan Rd, Dr Annie Besant Rd, Haji Ali, Marine Drive / Netaji Subhash Chandra Bose Rd, Pandurang Budhkar Marg …) → ordered loop polyline (≈ 25 km)
- [ ] Road segments with `name`, `highway` class, `is_control` (Coastal Road), `is_tunnel`
- [ ] POIs within 200 m: schools, hospitals, bus stops → `data/corridor/poi.geojson`
- [ ] Cache to `data/corridor/` (ODbL attribution in `LICENSES.md`)

### Generator (`synth/`)
- [ ] `camera.py`: intrinsics, distortion, extrinsics, homography helpers (shared with perception)
- [ ] `road.py`: metric ground texture tiles at 1 cm/px (asphalt, markings, seams, old patches), seeded per segment
- [ ] `defects.py`: procedural potholes/edge breaks/depressions + real cut-outs (seamlessClone); exact polygon area
- [ ] `distractors.py`: shadows, wet sheen, manholes, speed breakers, arrows
- [ ] `lifecycle.py`: pass-to-pass Markov transitions (unchanged/repaired/degraded/new)
- [ ] `motion.py`: speed profile, stops, GNSS noise (urban canyon ×2.5, tunnel outage), IMU
- [ ] `render.py`: frame = warp(ground) + sky/buildings + distortion + photometrics; GT masks
- [ ] `charuco.py`: rendered calibration views
- [ ] CLI: `python -m patchwork.synth --seed 7 --passes 3 [--segment worli-seaface] [--fps 30]`
- [ ] QA: contact sheet (`docs/midpoint/assets/synth_contact_sheet.jpg`), GT-mask overlay video snippet

### Datasets D1–D4 (starter for the midpoint)
- [ ] D1: 300 defects on the arterials (exact areas)
- [ ] D2: control segments (Coastal Road), zero defects
- [ ] D3: passes 1–3 with lifecycle events
- [ ] D4: 20 distractor clips (60 by Phase 8)

### Schema
- [ ] `schema/models.py` (pydantic) + `schema/ddl.sql` (PostGIS) + a test that they agree
- [ ] Tag `schema-v1`

## Exit criteria
| Check | Command |
|---|---|
| Full pass renders with truth | `make synth SEED=7 PASSES=1` → mp4 + gpx + imu + truth |
| Ground truth self-consistent | `pytest tests/synth` (re-projected GT polygon area == stated area within 0.5%) |
| QA contact sheet produced | file exists, reviewed by the user |
| Schema frozen | `git tag schema-v1` |
