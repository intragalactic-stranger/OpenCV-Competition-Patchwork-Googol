# 05: Defect record schema (the contract)

> **Status:** v1 draft. **Freezes at the end of Phase 1** (tag `schema-v1`). After the freeze, changes are additive only (new nullable columns), and each one needs a decision-log entry.

Perception writes it. The agent reads it. The register stores it. Defined once in `src/patchwork/schema/` (pydantic models) and `src/patchwork/schema/ddl.sql` (PostGIS DDL). A test asserts the two agree.

## 1. Entities

```
 pass 1──* clip 1──* observation *──1 defect (track) *──* work_package_item *──1 work_package 1──* approval
                                       │                                          │
                                       └──* status_event                          └──* ticket (mock filing)
 road_segment 1──* defect                                                         reinspection *──1 road_segment
 calibration 1──* clip          model 1──* observation
```

- **observation**: one sighting of a defect in one pass (what perception produces).
- **defect**: the persistent real-world thing (a *track*), linked across passes. Its status is the latest verification result.

## 2. `observation` (perception output, one row per defect per pass)

| Field | Type | Notes |
|---|---|---|
| `obs_id` | ULID (text) | Primary key, time-sortable |
| `defect_id` | ULID, nullable | Set by registration/matching |
| `pass_id`, `clip_id` | text | Provenance |
| `frame_idx`, `frame_ts` | int, timestamptz | Best frame (largest rectified footprint) |
| `geom` | geometry(Point, 4326) | Defect centroid on the ground |
| `geom_poly` | geometry(Polygon, 32643) | Footprint in metres (UTM 43N, Mumbai) |
| `gnss_hdop_proxy` | real | Estimated position uncertainty, m |
| `road_segment_id`, `road_name` | text | From snapping |
| `chainage_m`, `lateral_offset_m` | real | Along / across the road; negative lateral = left of centreline |
| `defect_type` | enum `pothole \| edge_break \| depression` | |
| `area_m2` | real, nullable | **Null when not measured** |
| `area_uncertainty_m2` | real | From pixel size at that range + mask-edge uncertainty |
| `length_m`, `width_m` | real | Min-area-rect axes on the rectified mask |
| `measurement_status` | enum `measured \| detected_not_measured \| obscured` | `detected_not_measured` when calibration is missing or stale, or the defect is outside the metric ROI |
| `severity` | enum `low \| medium \| high` | |
| `severity_confidence` | real 0–1 | |
| `detection_confidence` | real 0–1 | Mean mask probability inside the polygon |
| `material` | jsonb | `{"patch_thickness_m":0.05,"volume_m3":…,"mass_t":…,"wastage_pct":10,"assumption":"area x stated thickness; depth NOT measured"}` |
| `attributes` | jsonb | `{"wheel_path":bool,"water_pooling":bool,"near_bus_stop":bool,"prior_patch":bool,"source":"opencv-vlm\|bedrock\|rules"}` (Phase 6) |
| `crop_key`, `overlay_key`, `rectified_key` | text | S3 keys |
| `calibration_id`, `model_version`, `pipeline_version` | text | Reproducibility |
| `privacy_blurred` | bool | Must be true; the DB check constraint rejects false |
| `created_at` | timestamptz | |

## 3. `defect` (persistent track)

| Field | Type | Notes |
|---|---|---|
| `defect_id` | ULID | PK, cited by the agent in every claim |
| `first_seen_pass`, `last_seen_pass` | text | |
| `status` | enum `new \| unchanged \| repaired \| degraded \| obscured` | Latest verification result |
| `status_confidence` | real | |
| `latest_obs_id` | ULID | |
| `geom` | Point 4326 | Running robust mean of observations |
| `road_segment_id`, `road_name`, `chainage_m` | | |
| `latest_area_m2`, `latest_severity` | | Denormalised for fast queries |
| `open_work_package_id` | nullable | |

`status_event(defect_id, pass_id, from_status, to_status, evidence jsonb{iou, area_delta_pct, orb_inliers, before_key, after_key}, created_at)`

## 4. Agent-side entities

| Table | Key fields |
|---|---|
| `work_package` | `package_id`, `road_segment_id`, `defect_ids[]`, `total_area_m2`, `material` jsonb, `priority` 1–3, `exposure_score`, `rationale` text, `confidence`, `state` (`draft \| awaiting_approval \| approved \| rejected \| filed \| verified \| escalated`), `pdf_key`, `agent_run_id` |
| `approval` | `approval_id`, `package_id`, `sfn_execution_arn`, `decision` (`approve \| reject`), `decided_by`, `note`, `decided_at`, `is_override` |
| `ticket` | `ticket_id`, `package_id`, `external_ref` (mock), `filed_at`, `payload` jsonb |
| `reinspection` | `reinspection_id`, `road_segment_id`, `chainage_from`, `chainage_to`, `due_pass`, `reason`, `package_id` |
| `road_segment` | `road_segment_id`, `name`, `hierarchy` (OSM highway class), `geom` LineString, `is_control` bool, `is_tunnel` bool |
| `poi` | `poi_id`, `kind` (`school \| hospital \| bus_stop \| …`), `name`, `geom` |

## 5. Rules enforced in the database (not just in code)

- `CHECK (privacy_blurred)` on `observation`.
- `CHECK ((measurement_status = 'measured') = (area_m2 IS NOT NULL))`.
- `work_package.defect_ids` elements must exist in `defect`, enforced by a trigger. Lambda checks too, so this is the second line of defence for grounding.
- Unique `(clip_id, frame_idx, round(chainage_m,1), defect_type)` for idempotent reloads.

## 6. Severity and material defaults (v1, calibrated in Phase 3)

| Band | Rule v1 (area-based, before calibration) |
|---|---|
| low | area < 0.25 m² and not in the wheel path |
| medium | 0.25 ≤ area < 1.0 m², or low in the wheel path |
| high | area ≥ 1.0 m², or edge break > 2 m long, or medium with water pooling |

Material: `volume_m3 = area_m2 × patch_thickness_m (default 0.05)`; `mass_t = volume × 2.35 t/m³ (hot-mix density) × (1 + wastage 10%)`. Every work order prints this assumption.

## 7. Example (JSON as returned by `query_defects`)

```json
{
  "defect_id": "01JA7Q8M3Z4R6ZB1F0H2K5N9VX",
  "status": "unchanged",
  "road_name": "Dr Annie Besant Road",
  "chainage_m": 1843.2,
  "lateral_offset_m": 1.4,
  "latest_area_m2": 0.82,
  "area_uncertainty_m2": 0.07,
  "latest_severity": "medium",
  "measurement_status": "measured",
  "material": {"patch_thickness_m": 0.05, "volume_m3": 0.041, "mass_t": 0.106,
               "assumption": "area x stated thickness; depth NOT measured"},
  "attributes": {"wheel_path": true, "water_pooling": false, "near_bus_stop": true},
  "overlay_url": "https://…/overlays/01JA7Q….png",
  "model_version": "segb0-2026.10.20-a", "calibration_id": "cam01-v1"
}
```
