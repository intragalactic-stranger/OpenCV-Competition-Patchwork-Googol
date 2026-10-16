# Phase 1: Data and synthetic world

**Goal:** a reproducible synthetic Mumbai corridor with exact ground truth, plus open datasets mirrored and licensed. **Freeze the defect schema.**
**Midpoint track:** yes.

## Checklist

### Open data (`scripts/data/`)
- [x] ~~Indian Roads~~ → **Pothole Mix v2** instead (D-24: Indian Roads is GPL-2.0 with only 230 pothole images) → `data/raw/pothole_mix/` + `SOURCE.md` (URL, sha256, CC BY-NC 3.0), `scripts/data/fetch_pothole_mix.py`
- [x] RDD2022 India subset → `data/raw/rdd2022_india/` (CC BY-SA 4.0), `scripts/data/fetch_rdd2022_india.py`
- [ ] Optional: IndiaRDD2022 (Roboflow, CC BY 4.0): skipped, Pothole Mix covers the need for masks
- [x] Class map: **one `damage` class** (pothole, edge break, depression) + background, cracks = ignore (255). Written as `class_map.json` next to every model. Defect type comes from shape rules, not the network
- [ ] Blur pass over real images before upload: **not done for Pothole Mix** (road-surface close-ups, private bucket). Privacy blur was verified on RDD-India instead. To do before any public release (Phase 9)
- [x] Licences consolidated in [`main_docs/DATA-LICENSES.md`](../../DATA-LICENSES.md) (`data/` is git-ignored, so the file lives in `main_docs/`)

### Corridor (`synth/corridor.py`): done, 28.6 km loop, 33 segments, 84 POIs (`main_docs/midpoint/assets/corridor_map.png`)
- [x] Overpass download (`scripts/data/fetch_osm.py`) → loop routed through named-road waypoints on the directed road graph → 28.6 km polyline
- [x] Road segments with `name`, `highway` class, `is_control` (Coastal Road), `is_tunnel`
- [x] POIs within 200 m: schools, hospitals, bus stops → `data/corridor/poi.geojson`
- [x] Cache to `data/corridor/` (corridor.npz, segments.json/.geojson, poi.geojson); ODbL noted in `data/raw/osm/SOURCE.md`
- [x] Licences consolidated (see above)

### Generator (`synth/`): implemented as `camera.py` (shared), `synth/world.py` (road, features, defects, lifecycle, distractors), `render.py`, `motion.py`, `charuco.py`, `__main__.py`
- [x] `camera.py`: intrinsics, distortion, extrinsics, homography helpers (shared with perception)
- [x] Ground texture tiles at 1 cm/px (asphalt with wear and wheel-path polish, kerbs, pavers/parapets, lane markings, seams, old patches), deterministic per tile (`world.py`)
- [x] Procedural potholes, edge breaks and depressions with exact polygon area; 8× supersampled raster (bias < 1%)
- [ ] Real pothole cut-outs blended in (`seamlessClone`): not done; real appearance comes from training directly on Pothole Mix photos instead. Second half
- [x] Distractors: shadows and wet patches (per pass), manholes, speed breakers, tar seams, old patches (persistent)
- [ ] Painted arrows / zebra crossings: not done (lane markings and seams are). Second half, with the D4 clips
- [x] Lifecycle: pass-to-pass transitions (unchanged / repaired / degraded / new); repaired → rendered as a patch
- [x] `motion.py`: speed profile, stops, GNSS noise (urban canyon ×2.5, tunnel outage), IMU
- [x] `render.py`: frame = warp(ground) + sky/buildings + distortion + photometrics; GT masks
- [x] `charuco.py`: rendered calibration views
- [x] CLI: `python -m patchwork.synth --seed 7 --passes 1,2,3 [--segment NAME | --s-start/--s-end] [--fps 15] [--clip-m 3000]`
- [x] QA: contact sheet (`main_docs/midpoint/assets/synth_contact_sheet.jpg`) · [ ] GT-mask overlay video snippet (not done)

### Datasets D1–D4 (starter for the midpoint)
- [x] D1: two worlds with exact areas. Held-out world `seed11`: **179 defects** in pass 1 (120 potholes, 34 edge breaks, 25 depressions) → 251 visible defect instances over 2 passes; `seed07` is the training world
- [x] D2: Coastal Road control section, 10.1 km per pass, zero defects (20.2 km over 2 evaluated passes)
- [x] D3: 3 passes rendered per world; passes 1→2 evaluated (`seed11`: 44 repaired, 29 degraded, 5 new)
- [~] D4: distractors (shadows, wet, manholes, seams, old patches, speed breakers) are in **every** pass; plus `hard_neg_val`, 480 look-alike frames from the training world. Dedicated distractor clips: second half

### Schema
- [x] `schema/models.py` (pydantic) + `schema/ddl.sql` (PostGIS) + `tests/test_schema.py` checks that they agree
- [x] Tag `schema-v1.1` (v1 + the additive `approval_request` table, D-28)

## Exit criteria
| Check | Command |
|---|---|
| Full pass renders with truth | `make synth SEED=7 PASSES=1` → mp4 + gpx + imu + truth |
| Ground truth self-consistent | `pytest tests/synth` (re-projected GT polygon area == stated area within 0.5%) |
| QA contact sheet produced | file exists, reviewed by the user |
| Schema frozen | `git tag schema-v1` |
