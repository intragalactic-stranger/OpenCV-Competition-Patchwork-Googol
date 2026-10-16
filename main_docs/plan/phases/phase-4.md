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
- [x] modules: storage, network, db, batch, pipeline (incl. ingest + approval + a CloudWatch dashboard), viewer · [ ] alarms (below)
- [x] Step Functions `process-pass`: read manifest → Batch perceive array (.sync) → Batch assemble (.sync: register + viewer). No Lambda needed
- [ ] Batch / Step Functions failure alarm (no SQS, so no DLQ: EventBridge starts Step Functions directly, and Batch retries + the unique index give idempotency). Second half
- [x] `terraform apply` works incrementally (≈ 70 resources) · [ ] destroy from clean verified once (Phase 9)

### Viewer (midpoint)
- [x] `viewer/index.html`: MapLibre + Amazon Location style; defects coloured by severity; popup with evidence image, m² ± uncertainty, material, status, IDs; synthetic-data banner
- [~] No API needed for the midpoint: the assemble job publishes the register as GeoJSON (`pipeline/publish.py`). API Gateway comes with the console
- [x] Served from CloudFront (private bucket + OAC)

### Pipeline metrics
- [x] CloudWatch EMF metrics printed by `pipeline/batch.py` (`emf()`) from the perceive and assemble jobs
- [x] Small CloudWatch dashboard (pipeline only), in `modules/pipeline`

## Exit criteria
| Check | How |
|---|---|
| Full-corridor pass processed end to end on AWS | `make upload-pass PASS=1` → SFN success → rows in Aurora |
| Idempotency | Re-upload the same clip → 0 new rows; Spot-interruption simulation (kill job) → retry → no duplicates |
| Viewer live | CloudFront URL shows defects; screenshot to `main_docs/midpoint/assets/` |
| Processing time and cost per km | Reported in the progress report (from metrics + Cost Explorer) |

## Exit status at the midpoint (2026-10-14)
- ✅ Full corridor end to end on AWS: held-out survey, 2 passes, 56.8 km, 15–17 min per pass, register in Aurora, map on CloudFront.
- ✅ Spot interruptions: every job definition retries up to 3 times (the training job survived 3 real interruptions); the unique index (`ON CONFLICT DO NOTHING`) means a re-run cannot double-insert an observation.
- ⏭ Not yet run as a deliberate test: re-upload the same clip and count 0 new rows; kill a job mid-run. Planned with the Phase 9 hardening, together with `terraform destroy` from clean.
- ✅ Processing time and cost per km: 147 s/km, $0.0021/km ([04](../../midpoint/04-RESULTS-AND-OUTPUTS.md), [02](../../midpoint/02-COST-REPORT.md)).
