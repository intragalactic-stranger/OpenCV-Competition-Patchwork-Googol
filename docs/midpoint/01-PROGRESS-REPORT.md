# Progress report

> Living document, updated at the end of every work session.
> **Last updated:** 2026-10-13 · **Current phase:** Phase 2 ✅ (geometry, triage, privacy, localisation) · Phase 3 🔄 (model training running on AWS) · Phase 4 🔄 (AWS base stack live) · **Overall midpoint progress:** ▓▓▓▓▓░░░░░ 50%

## At a glance

| Area | Status | Notes |
|---|---|---|
| Planning & design docs | ✅ | `docs/plan/*`, `docs/midpoint/*`, decisions D-01…D-27 |
| Repo, environment, tests | ✅ | Python 3.12 (uv); `make check`: lint + 23 tests green |
| OpenCV 5 verified | ✅ | `ENGINE_NEW` runs a **real SegFormer-B0** (max difference 1.6e-6 vs onnxruntime, 100% identical pixel decisions); `ENGINE_CLASSIC` cannot load it |
| AWS access + guardrails | ✅ | PowerUserAccess plus a permissions boundary (no role can grant itself admin). **Real-money budget alarm at $0.01**: everything runs on promotional credits |
| AWS base stack (Terraform) | ✅ | VPC (no NAT), 3 S3 buckets, 2 ECR repos, Batch on Graviton **Spot** (0–32 vCPU), CloudWatch logs; 50 resources, all tagged |
| Survey corridor from OpenStreetMap | ✅ | 28.6 km loop, 10.1 km control section, 84 POIs |
| Synthetic survey data | ✅ | **2 worlds × 3 passes × 28.6 km rendered on AWS Batch** (60 clips, about 8 GB, 77 ms/frame on Graviton). Seed 07 for training, seed 11 held out for testing |
| Real data | ✅ | RDD2022-India (9,665 photos, boxes); **Pothole Mix** (4,340 photos with pixel masks) |
| Calibration (ChArUco) | ✅ | RMS 0.164 px; focal length within 0.02% of truth |
| Bird's-eye view + m² | ✅ | **Geometry area error 2.1% (target ≤ 5%)** |
| Frame triage | ✅ | Visual odometry on the road plane; **297 frames/km, 0% defects lost**, every defect in ≥ 2 kept frames |
| Privacy blur | ✅ | YuNet faces + text/plate detector; 4/4 test plates blurred; 0 of 112 potholes blurred by mistake |
| Localisation | ✅ | Kalman filter + smoother on the route; **3.9 m median error vs 9.1 m for raw GPS** (target ≤ 8 m) |
| Segmentation model | 🔄 | SegFormer-B0, **CPU training on Batch Graviton Spot** (no GPU, owner's choice). See [model card](07-MODEL-CARD.md) |
| Cloud pipeline (Step Functions, Aurora) + map viewer | ⏭ | Phase 4 remainder |
| Agent slice + run A/B (stretch) | ⏭ | Amazon Nova on Bedrock; account verification by AWS pending |

## ✅ Achieved

| Date | What | Evidence |
|---|---|---|
| 2026-10-12 | Proposal analysed; build adapted to open + synthetic data; full design written | [`plan/`](../plan/) |
| 2026-10-12 | OpenCV 5.0.0 verified (smoke test) | [`assets/opencv5_smoke.md`](assets/opencv5_smoke.md) |
| 2026-10-12 | Survey corridor from OpenStreetMap; synthetic dashcam generator with exact ground truth | [`assets/corridor_map.png`](assets/corridor_map.png), [`assets/synth_contact_sheet.jpg`](assets/synth_contact_sheet.jpg) |
| 2026-10-12 | Calibration (RMS 0.164 px) and bird's-eye geometry (**2.1% area error**) | [`04-RESULTS`](04-RESULTS-AND-OUTPUTS.md) |
| 2026-10-13 | **AWS live**: Terraform state bucket, budget alarm, VPC, S3, ECR, Batch Graviton Spot | `infra/terraform/` |
| 2026-10-13 | **Full synthetic survey rendered in the cloud**: 60 clips (2 worlds × 3 passes × 28.6 km) by Batch array jobs, about 15 min each | `scripts/aws/submit_synth.py` |
| 2026-10-13 | **Frame triage** with road-plane visual odometry (297 frames/km, 0% recall loss) | [`04-RESULTS`](04-RESULTS-AND-OUTPUTS.md) |
| 2026-10-13 | **Privacy blur** (faces + plates) | `src/patchwork/perception/privacy.py` |
| 2026-10-13 | **Localisation**: 3.9 m median, better than raw GPS (9.1 m) | [`04-RESULTS`](04-RESULTS-AND-OUTPUTS.md) |
| 2026-10-13 | **Real SegFormer-B0 runs in OpenCV 5 `ENGINE_NEW`**, identical to onnxruntime (1.6e-6) and as fast (381 vs 396 ms per frame strip, 4 vCPU); the 4.x-style engine cannot load it | `training/parity.py` |
| 2026-10-13 | Cost reporting splits usage / credits / real money; **real money paid: $0.00** | [`02-COST-REPORT`](02-COST-REPORT.md) |

## 🔄 In progress

| What | Phase | Notes |
|---|---|---|
| Segmentation training run `seg-v1` (prepare → train on Batch, CPU) | 3 | Results land in the [model card](07-MODEL-CARD.md) and the results table automatically |
| Full-corridor triage + localisation evaluation on the held-out world (incl. 3.1 km tunnel) | 2 | |

## ⏭ Next in the pipeline

1. Model results → end-to-end area error and recall on the held-out world (D1), false positives per km on the Coastal Road control section (D2).
2. Phase 4: Step Functions pipeline, register in Aurora Serverless PostGIS, map viewer on CloudFront.
3. Agent preview on Amazon Nova once AWS finishes verifying the account for Bedrock.

## ⚠️ Blockers / owner actions

| Item | Needed for | Status |
|---|---|---|
| Bedrock: "account is being verified" (AWS-side check on new accounts) | Agent slice (Nova) | ⏳ AWS; usually clears within hours. If it persists, write to aws-verification@amazon.com |
| Check credit balance / expiry in **Billing → Credits** monthly | Zero-real-cost rule (D-27) | owner, about 1 minute a month |
| SageMaker GPU quota requests (filed before the CPU-only decision) | not needed | open AWS support cases; harmless, can be ignored |

## Deviations from the proposal (summary)

See [`plan/02-requirements.md §4`](../plan/02-requirements.md#4-what-changed-from-the-proposal-and-why) and the decision log [`plan/11`](../plan/11-decisions-and-risks.md). Main points:

- Synthetic survey passes over the real corridor replace physical drives and tape measurements, which gives exact ground truth.
- LLMs are Amazon Nova.
- Video is 15 fps, and triage targets are per km (D-23).
- Training runs on CPU, not GPU (D-25).
- Real masks come from Pothole Mix, which is research-licensed (D-24).
- Everything is paid from promotional credits (D-27).

## Session log

| Date | Session summary |
|---|---|
| 2026-10-12 (a) | Proposal analysed; decisions; all docs; Phase 0 (repo, env, OpenCV 5 smoke, IaC, cost report) |
| 2026-10-12 (b) | IAM boundary guard; Amazon Nova; corridor; synthetic world + renderer; RDD2022-India; calibration; bird's-eye view; pitch estimation; oracle geometry eval (2.1%) |
| 2026-10-13 | AWS live (bootstrap + dev stack); arm64 images; 60 synthetic clips rendered on Batch; triage, privacy, localisation; Pothole Mix; SegFormer-B0 training pipeline (CPU) + OpenCV 5 parity; model card; credits-only cost guard |
