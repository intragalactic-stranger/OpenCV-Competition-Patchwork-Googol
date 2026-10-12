# Phase 4: Register and cloud pipeline (midpoint demo backbone)

**Goal:** upload a synthetic pass to S3, and minutes later see measured defects on a map, all on AWS, all via Terraform.
**Midpoint track:** yes. This phase *is* the proposal's week-4 midpoint check-in.

## Checklist

### Register
- [ ] `register/repo.py`: Data API client (aws) + psycopg (local), same interface
- [ ] DDL migration runner (`register/migrate.py`), PostGIS extension, `schema-v1`
- [ ] Load corridor road segments + POIs
- [ ] Observation load (one transaction), within-pass dedup, road snapping (Amazon Location SnapToRoads → PostGIS fallback)
- [ ] Basic defect tracks: link to the existing defect within 3 m / same segment (full cross-pass matching is Phase 6)

### Container
- [ ] `docker/batch.Dockerfile`: python:3.12-slim arm64, OpenCV 5, onnxruntime (parity fallback), our package
- [ ] `docker buildx` for linux/arm64 (QEMU on this x86 box) → ECR
- [ ] Entry point `python -m patchwork.pipeline.batch_entry --clip s3://…`

### Terraform (`infra/terraform/envs/dev`)
- [ ] modules: storage, network, db, ingest, batch, pipeline, viewer, observability
- [ ] Step Functions `process-clip`: idempotency → Batch .sync (retry on Spot) → register-load Lambda → match Lambda → metrics
- [ ] DLQ alarm, Batch failure alarm
- [ ] `terraform apply` from a clean state works; `terraform destroy` too (verified once)

### Viewer (midpoint)
- [ ] `viewer/index.html`: MapLibre + Amazon Location style; defects as circles coloured by severity; popup with overlay image, m² ± uncertainty, material, status, IDs
- [ ] `GET /defects?bbox=` and `GET /defects/{id}` (Lambda via Data API)
- [ ] Served from CloudFront

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
