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

### Corridor (`synth/corridor.py`): done, 28.6 km loop, 33 segments, 84 POIs (`docs/midpoint/assets/corridor_map.png`)
- [x] Overpass download (`scripts/data/fetch_osm.py`) → loop routed through named-road waypoints on the directed road graph → 28.6 km polyline
- [x] Road segments with `name`, `highway` class, `is_control` (Coastal Road), `is_tunnel`
- [x] POIs within 200 m: schools, hospitals, bus stops → `data/corridor/poi.geojson`
- [x] Cache to `data/corridor/` (corridor.npz, segments.json/.geojson, poi.geojson); ODbL noted in `data/raw/osm/SOURCE.md`
- [ ] `data/LICENSES.md` consolidating all sources

### Generator (`synth/`): implemented as `camera.py` (shared), `synth/world.py` (road, features, defects, lifecycle, distractors), `render.py`, `motion.py`, `charuco.py`, `__main__.py`
- [x] `camera.py`: intrinsics, distortion, extrinsics, homography helpers (shared with perception)
- [x] Ground texture tiles at 1 cm/px (asphalt with wear and wheel-path polish, kerbs, pavers/parapets, lane markings, seams, old patches), deterministic per tile (`world.py`)
- [x] Procedural potholes, edge breaks and depressions with exact polygon area; 8× supersampled raster (bias < 1%)
- [ ] Real pothole cut-outs from Indian Roads blended in (`seamlessClone`): needs the dataset
- [x] Distractors: shadows and wet patches (per pass), manholes, speed breakers, tar seams, old patches (persistent)
- [ ] Painted arrows / zebra crossings
- [x] Lifecycle: pass-to-pass transitions (unchanged / repaired / degraded / new); repaired → rendered as a patch
- [x] `motion.py`: speed profile, stops, GNSS noise (urban canyon ×2.5, tunnel outage), IMU
- [x] `render.py`: frame = warp(ground) + sky/buildings + distortion + photometrics; GT masks
- [x] `charuco.py`: rendered calibration views
- [x] CLI: `python -m patchwork.synth --seed 7 --passes 1,2,3 [--segment NAME | --s-start/--s-end] [--fps 15] [--clip-m 3000]`
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
