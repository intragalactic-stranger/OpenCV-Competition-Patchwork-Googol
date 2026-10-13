# Phase 4: Register and cloud pipeline (midpoint demo backbone)

**Goal:** upload a synthetic pass to S3, and minutes later see measured defects on a map, all on AWS, all via Terraform.
**Midpoint track:** yes. This phase *is* the proposal's week-4 midpoint check-in.

## Checklist

### Register
- [x] `register/dataapi.py`: Data API client (the only access path; no local psycopg needed)
- [x] DDL migration (`dataapi migrate`, `$$`-aware splitter), PostGIS, schema v1 (+ v1.1 `approval_request`, D-28)
- [x] Load corridor road segments (33) + POIs (84)
- [x] Observation load, idempotent via unique index (`ON CONFLICT DO NOTHING`); within-pass dedup in `assemble`; road snapping = route chainage (the survey route is known). Amazon Location SnapToRoads not needed
- [x] Basic cross-pass tracks: link to an existing defect within 8 m on the same segment (localisation p90 6.5 m); unchanged/degraded status events

### Container
- [x] `docker/batch.Dockerfile`: python:3.12-slim arm64, OpenCV 5, our package, YuNet, calibration, viewer
- [x] `docker buildx` for linux/arm64 (QEMU on this x86 box) → ECR (`patchwork-batch`, `patchwork-train`)
- [x] Entry point `python -m patchwork.pipeline.batch perceive|assemble` (D-29)

### Terraform (`infra/terraform/envs/dev`)
- [x] modules: storage, network, db, batch, pipeline (incl. ingest + approval), viewer · [ ] observability (dashboard, alarms)
- [x] Step Functions `process-pass`: read manifest → Batch perceive array (.sync) → Batch assemble (.sync: register + viewer). No Lambda needed
- [ ] DLQ alarm, Batch failure alarm
- [x] `terraform apply` works incrementally (≈ 70 resources) · [ ] destroy from clean verified once (Phase 9)

### Viewer (midpoint)
- [x] `viewer/index.html`: MapLibre + Amazon Location style; defects coloured by severity; popup with evidence image, m² ± uncertainty, material, status, IDs; synthetic-data banner
- [~] No API needed for the midpoint: the assemble job publishes the register as GeoJSON (`pipeline/publish.py`). API Gateway comes with the console
- [x] Served from CloudFront (private bucket + OAC)

### Pipeline metrics
- [ ] CloudWatch EMF metrics: `KmProcessed`, `FramesKept`, `DefectsFound`, `StageSeconds{stage}`, `EstimatedCostUSD`
- [ ] Small CloudWatch dashboard (pipeline only)

## Exit criteria
| Check | How |
|---|---|
| Full-corridor pass processed end to end on AWS | `make upload-pass PASS=1` → SFN success → rows in Aurora |
| Idempotency | Re-upload the same clip → 0 new rows; Spot-interruption simulation (kill job) → retry → no duplicates |
| Viewer live | CloudFront URL shows defects; screenshot to `docs/midpoint/assets/` |
| Processing time and cost per km | Reported in the progress report (from metrics + Cost Explorer) |
