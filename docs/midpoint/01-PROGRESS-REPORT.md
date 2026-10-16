# Progress report

> Living document, updated at the end of every work session.
> **Last updated:** 2026-10-14 · **Current phase:** midpoint vertical slice complete, on `seg-v3` (Phases 0–4 ✅, 5a ✅) · **Overall midpoint progress:** ▓▓▓▓▓▓▓▓▓▓ 100% of the midpoint scope

## At a glance

| Area | Status | Notes |
|---|---|---|
| Planning & design docs | ✅ | `docs/plan/*`, `docs/midpoint/*`, decisions D-01…D-30 |
| Repo, environment, tests | ✅ | Python 3.12 (uv); `make check` (lint + tests) |
| OpenCV 5 | ✅ | The **trained** SegFormer-B0 runs in `ENGINE_NEW`, identical to onnxruntime (2.0e-5); `ENGINE_CLASSIC` cannot load it |
| AWS guardrails | ✅ | Permissions boundary on every role; **real money paid $0.00**, all usage on promotional credits; `patchwork-real-spend` alarm |
| AWS stack (Terraform) | ✅ | 42 resources in 13 services ([03](03-SERVICES-USED.md)): VPC (no NAT), S3, ECR, Batch Graviton Spot, Step Functions, EventBridge, Aurora Serverless v2 (PostGIS, auto-pause), CloudFront, Amazon Location, Bedrock (Nova), CloudWatch |
| Synthetic survey data | ✅ | 2 worlds × 3 passes × 28.6 km rendered on Batch; seed 07 for training, seed 11 held out |
| Geometry (calibration, bird's-eye view, m²) | ✅ | Oracle-mask area error **2.1%** (target ≤ 5%) |
| Triage, privacy blur, localisation | ✅ | 284 frames/km with 0% defects lost; plates and faces blurred; **2.6 m** median position error |
| Segmentation model `seg-v3` | ✅ trained · ⚠️ IoU below aim | CPU only: `seg-v2` (12 epochs, 3.9 h) fine-tuned with look-alike frames (4 epochs, 2.7 h, survived 3 Spot interruptions). IoU 0.50 on real photos, 0.57 on synthetic; false alarms on look-alikes 86 → 41 of 480. [Model card](07-MODEL-CARD.md) |
| **End-to-end cloud pipeline** | ✅ | Upload → EventBridge → Step Functions → Batch → Aurora → viewer; **56.8 km in two passes, 15–17 min per pass** |
| End-to-end metrics | ⚠️ mixed | Recall **0.94** ✅ · control-section false positives **0.30/km** ✅ (was 3.87) · cost **$0.0021/km** ✅ · area MAPE 27.8% ❌ (was 33.7%) · re-ID F1 0.73 (was 0.57) · whole-survey false positives 3.1/km (was 10). See [04 §3](04-RESULTS-AND-OUTPUTS.md#3-commentary-honest-reading-of-the-numbers) |
| Map viewer | ✅ | https://d3mt6jrs1ynczo.cloudfront.net (synthetic data, labelled) |
| Agent slice on Amazon Nova + approval gate | ✅ | Run A/B on **`seg-v3` pipeline output**: priority 2 → 1, hot-mix 0.05 → 0.40 t; road-wide plan of 24 packages; approve → MOCK ticket, reject → override recorded; unknown IDs rejected |

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
| 2026-10-13 | **Cloud pipeline live**: S3 upload → EventBridge → Step Functions → Batch (perceive ×10 in parallel, assemble) → Aurora register → CloudFront viewer | [`assets/sfn_run.png`](assets/sfn_run.png), [`assets/viewer.png`](assets/viewer.png) |
| 2026-10-13 | **Agent slice on Amazon Nova** with grounding guard (tool + database), approval gate via Step Functions task token, mock filing | [`assets/ablation_ab.md`](assets/ablation_ab.md) |
| 2026-10-13 | **`seg-v2` trained on CPU** (Graviton Spot, 3.9 h); model card | [`07-MODEL-CARD`](07-MODEL-CARD.md) |
| 2026-10-13 | **Held-out survey end to end, 2 passes, 56.8 km**: recall 0.95, $0.0019/km; false positives analysed (shadows and wet patches) | [`04-RESULTS`](04-RESULTS-AND-OUTPUTS.md) |
| 2026-10-13 | Run A/B on pipeline output passes; approve/reject exercised on pipeline packages | [`assets/ablation_ab.md`](assets/ablation_ab.md) |
| 2026-10-13 | **Hard-negative fine-tune `seg-v3`** (CPU, 2.7 h; resumed from S3 checkpoints after 3 Spot interruptions). Same survey re-run through the cloud: false alarms 10.05 → 3.1 per km, control section 0.30/km (**target met**), area MAPE 33.7% → 27.8%, re-ID F1 0.57 → 0.73 | [`07-MODEL-CARD`](07-MODEL-CARD.md), [`04-RESULTS` §2.4c, §3](04-RESULTS-AND-OUTPUTS.md) |
| 2026-10-14 | Register, map viewer, run A/B and agent demo refreshed on `seg-v3` output (24 work packages; one approved → MOCK ticket, one rejected) | [`assets/viewer.png`](assets/viewer.png), [`assets/ablation_ab.md`](assets/ablation_ab.md) |

## 🔄 In progress

Nothing running. The register, the map viewer, the run A/B and the agent demo all use the `seg-v3` survey (refreshed 2026-10-14). Re-run `make cost-report` once the last Spot charges reach Cost Explorer (24–48 h).

## ⏭ Next

1. Manhole covers into the look-alike set; merge split masks of one defect before they reach the register (the two largest remaining false-alarm groups).
2. Depression measurement (soft boundaries, larger input, mask fusion across frames) for the area error.
3. Second half: see [06-NEXT-STEPS](06-NEXT-STEPS.md).

## ⚠️ Blockers / owner actions

| Item | Needed for | Status |
|---|---|---|
| Bedrock account verification | Agent slice (Nova) | ✅ cleared |
| Check credit balance / expiry in **Billing → Credits** monthly | Zero-real-cost rule (D-27) | owner, about 1 minute a month |
| Close the old SageMaker GPU quota requests (Support Center → Cases) | **Second-half GPU training**: they use up the account's limit of open quota requests, so the EC2 G-instance request (`08` §5) cannot be filed until they are closed | owner, before the second half |

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
| 2026-10-13 (a) | AWS live (bootstrap + dev stack); arm64 images; 60 synthetic clips rendered on Batch; triage, privacy, localisation; Pothole Mix; SegFormer-B0 training pipeline (CPU) + OpenCV 5 parity; model card; credits-only cost guard |
| 2026-10-13 (b) | Aurora register, Step Functions pipeline, viewer, agent slice + approval gate; `seg-v2` trained; held-out survey (2 passes) through the cloud; end-to-end metrics, false-positive analysis; register within-pass linking fix |
| 2026-10-13 (c) | Service mappings + second-half projection (`08`), reviewer walkthrough (`09`); hard-negative mining; `seg-v3` fine-tune; survey re-run on `seg-v3`; before/after figures; cost report accounts for data-transfer credits |
| 2026-10-14 | Register reset (owner-authorised) and rebuilt from the `seg-v3` survey (278 defects); viewer republished; run A/B and road-wide agent demo re-run on `seg-v3`; approve/reject exercised; 25 orphaned approval workflows from the old demo stopped |
| 2026-10-14 (b) | Docs audit: phase checklists 0–5 brought up to the as-built state (deviations and open items marked), `docs/DATA-LICENSES.md` added, "as built" notes on plan pages 03/04/08/09/10, schema tagged `schema-v1.1`. Open items found: Pothole Mix not yet privacy-blurred, `lraspp` licence-clean model not trained, failure alarms and a re-upload idempotency test not yet run (all second half / Phase 9) |
| 2026-10-16 | **Second half delivered; see [FINAL-REPORT](../FINAL-REPORT.md).** SegFormer-B2 trained on SageMaker GPU (`seg-v4`); matcher v2 and pass closing; full agent toolset; 40-scenario suite; failure alarms; final survey through the cloud on a fresh register database; repair verification loop; CI on GitHub |
