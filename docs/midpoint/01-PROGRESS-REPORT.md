# Progress report

> Living document, updated at the end of every work session.
> **Last updated:** 2026-10-12 · **Current phase:** Phase 1 (synthetic world) ✅ mostly done; Phase 2 (geometry) 🔄 · **Overall midpoint progress:** ▓▓▓░░░░░░░ 30%

## At a glance

| Area | Status | Notes |
|---|---|---|
| Planning & design docs | ✅ | `docs/plan/*`, `docs/midpoint/*` |
| Repo, environment, tests | ✅ | Python 3.12 (uv); `make check`: lint + 15 tests green |
| OpenCV 5 verified | ✅ | New DNN engine loads dynamic-shape SegFormer-style graph (parity 3.8e-6); classic engine cannot. [Evidence](assets/opencv5_smoke.md) |
| AWS access + guardrails | 🔄 | Role attached; IAM privilege-escalation guard applied and tested; **waiting for `PowerUserAccess`** on the role (owner action) |
| Survey corridor from OpenStreetMap | ✅ | 28.6 km loop, 10.1 km control section, 84 POIs. [Map](assets/corridor_map.png) |
| Synthetic dashcam generator | ✅ | Exact ground truth (area, position, state); passes 1–N with repairs, degradation, new defects. [Contact sheet](assets/synth_contact_sheet.jpg) |
| Open datasets | 🔄 | RDD2022-India ✅ (9,665 images, 3,187 pothole boxes). Indian Roads (masks) ⏭ |
| Calibration (ChArUco) | ✅ | RMS 0.164 px; focal length within 0.02% of truth. [Figure](assets/calibration.png) |
| Bird's-eye view + m² measurement | ✅ | **Geometry area error 2.1% (target ≤ 5%)** with per-frame pitch estimated from lane lines. [Figure](assets/bev_measure.png) |
| Frame triage, privacy blur, localisation | ⏭ | Phase 2 remainder |
| Segmentation model (SageMaker → ONNX → OpenCV 5) | ⏭ | Needs AWS |
| AWS pipeline + map viewer | ⏭ | Needs AWS |
| Agent slice + run A/B (stretch) | ⏭ | Amazon Nova on Bedrock (owner's choice) |

## ✅ Achieved

| Date | What | Evidence |
|---|---|---|
| 2026-10-12 | Proposal analysed; build adapted to open + synthetic data | [`plan/02-requirements.md`](../plan/02-requirements.md) |
| 2026-10-12 | Full design written (architecture, data, schema, perception, agent, evaluation, AWS/cost) | [`plan/`](../plan/) |
| 2026-10-12 | **OpenCV 5.0.0 verified**: new DNN engine runs a SegFormer-style graph with dynamic input size (parity 3.8×10⁻⁶ vs onnxruntime); the classic engine cannot load it | [`assets/opencv5_smoke.md`](assets/opencv5_smoke.md) |
| 2026-10-12 | AWS: role attached; **permissions boundary** so no Patchwork role can ever grant itself admin (verified by 5 deny tests) | [`plan/09 §1.1`](../plan/09-aws-infra-and-cost.md) |
| 2026-10-12 | **Survey corridor** routed on real OpenStreetMap data: 28.6 km, Coastal Road control section driven once, tunnels flagged (no GNSS) | [`assets/corridor_map.png`](assets/corridor_map.png) |
| 2026-10-12 | **Synthetic dashcam generator**: 1080p video, lens distortion, GNSS (1 Hz, urban-canyon error, tunnel outages), IMU (100 Hz), exact ground-truth masks and areas; defect lifecycle across passes | [`assets/synth_contact_sheet.jpg`](assets/synth_contact_sheet.jpg) |
| 2026-10-12 | RDD2022-India downloaded selectively (0.5 GB of a 13 GB archive, via HTTP range requests) | `scripts/data/fetch_rdd2022_india.py` |
| 2026-10-12 | **Calibration** from ChArUco views: RMS 0.164 px, focal length within 0.02% | [`assets/calibration.png`](assets/calibration.png) |
| 2026-10-12 | **Geometry validated**: true masks through our calibration + bird's-eye view measure area with **2.1% mean error** (target ≤ 5%); per-frame pitch from lane-line geometry beats a fixed pitch (4.4%) | [`04-RESULTS`](04-RESULTS-AND-OUTPUTS.md), [`assets/bev_measure.png`](assets/bev_measure.png) |

## 🔄 In progress

| What | Phase | Notes |
|---|---|---|
| Frame triage, privacy blur, localisation (GNSS + map-matching) | 2 | |
| Indian Roads dataset (pothole masks) | 1 | Locating source + licence |
| AWS bootstrap (state bucket + $300 budget, alerts to the owner's address) | 0 | Blocked on `PowerUserAccess` |

## ⏭ Next in the pipeline

1. Finish Phase 2 (triage, privacy blur, localisation) and render the full D1/D2 datasets.
2. As soon as AWS permissions land: bootstrap + budget, then the SageMaker segmentation training (Phase 3).
3. Cloud pipeline on Batch + Step Functions + Aurora PostGIS, and the map viewer (Phase 4).

## ⚠️ Blockers / owner actions

| Item | Needed for | Status |
|---|---|---|
| Attach **`PowerUserAccess`** to role `patchwork-dev-box` | All AWS work (S3, Budgets, SageMaker, Batch…) | ⚠️ owner: the role currently has only the IAM-scoped inline policy |
| Activate the `Project` cost-allocation tag / Cost Explorer | Cost report by tag | ⏭ owner (payer account) |

## Deviations from the proposal (summary)

See [`plan/02-requirements.md §4`](../plan/02-requirements.md#4-what-changed-from-the-proposal-and-why) and the decision log [`plan/11`](../plan/11-decisions-and-risks.md). Main points: synthetic survey passes over the real corridor replace physical drives and tape measurements (exact ground truth); LLMs are Amazon Nova on Bedrock; synthetic video at 15 fps.

## Session log

| Date | Session summary |
|---|---|
| 2026-10-12 (a) | Proposal analysed; decisions (ap-south-1, $300/month, instance role, open + synthetic data); all docs; Phase 0: repo, env, OpenCV 5 smoke (4/4), AWS CLI + Terraform, bootstrap IaC, cost-report automation |
| 2026-10-12 (b) | Role attached; IAM boundary guard; LLM switched to Amazon Nova; corridor from OSM; synthetic world, renderer, motion, GNSS/IMU, generator CLI; RDD2022-India; calibration; bird's-eye view; pitch estimation; oracle geometry evaluation (2.1%); evidence figures; results table generated from code |
