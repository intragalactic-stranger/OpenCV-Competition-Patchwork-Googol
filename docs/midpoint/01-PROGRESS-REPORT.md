# Progress report

> Living document, updated at the end of every work session.
> **Last updated:** 2026-10-12 · **Current phase:** Phase 0 (Foundations), waiting on AWS access · **Overall midpoint progress:** ▓░░░░░░░░░ 8%

## At a glance

| Area | Status | Notes |
|---|---|---|
| Planning & design docs | ✅ | `docs/plan/*` (11 docs + 10 phase checklists), `docs/midpoint/*` |
| Repo + environment | ✅ | Python 3.12 (uv), `make check` green |
| OpenCV 5 verified (DNN new engine, ChArUco, YuNet, ORB) | ✅ | 4/4 checks: [evidence](assets/opencv5_smoke.md) |
| AWS tooling (CLI v2, Terraform 1.16) | ✅ | Installed |
| AWS access + budget guardrails | ⚠️ | Terraform written and validated; **waiting on the instance role** (owner action) |
| Cost reporting automation | ✅ | `make cost-report` ready; runs once credentials exist |
| Synthetic corridor + passes | ⏭ | |
| Open datasets mirrored | ⏭ | |
| Geometry: calibration → IPM → m² | ⏭ | |
| Segmentation model (SageMaker → ONNX → OpenCV 5) | ⏭ | |
| AWS pipeline (S3 → SFN → Batch → Aurora) | ⏭ | |
| Map viewer | ⏭ | |
| Agent slice + run A/B (stretch) | ⏭ | |

## ✅ Achieved

| Date | What | Evidence |
|---|---|---|
| 2026-10-12 | Proposal analysed; build adapted to open + synthetic data (no field capture) | [`plan/01-project-brief.md`](../plan/01-project-brief.md), [`plan/02-requirements.md`](../plan/02-requirements.md) |
| 2026-10-12 | Architecture, data strategy, schema, perception, agent, evaluation and AWS/cost designs written | [`plan/`](../plan/) |
| 2026-10-12 | Midpoint scope defined (MUST / SHOULD / WON'T) | [`00-MIDPOINT-SCOPE.md`](00-MIDPOINT-SCOPE.md) |
| 2026-10-12 | **OpenCV 5.0.0 verified.** A SegFormer-style ONNX graph with dynamic input size runs in the **new DNN engine** and matches onnxruntime to 4×10⁻⁶. The **classic engine cannot load it**, which confirms why the project needs OpenCV 5. | [`assets/opencv5_smoke.md`](assets/opencv5_smoke.md) |
| 2026-10-12 | ChArUco calibration through a distorted virtual camera recovers the focal length to within 0.04% (RMS 0.17 px) | same |
| 2026-10-12 | Same OpenCV 5 version confirmed for x86 and **Arm (Graviton)** | PyPI wheels `5.0.0.93` |
| 2026-10-12 | Infrastructure-as-code bootstrap (state bucket + $300 budget with 4 alerts) written and validated | `infra/terraform/bootstrap/` |
| 2026-10-12 | Automated cost report from Cost Explorer (by service, by phase, cost per km) | `scripts/cost_report.py` |

## 🔄 In progress

| What | Phase | Notes |
|---|---|---|
| AWS bootstrap apply | 0 | Runs as soon as the instance role is attached |

## ⏭ Next in the pipeline

1. Apply the Terraform bootstrap → budget live → first cost report.
2. Synthetic corridor from OpenStreetMap (Coastal Road, Worli Seaface, Haji Ali, Marine Drive) and the first rendered pass with exact ground truth.
3. Download and licence-check the Indian Roads and RDD2022-India datasets.
4. Calibration → bird's-eye view → square-metre measurement with oracle masks.

## ⚠️ Blockers / owner actions

| Item | Needed for | How | Status |
|---|---|---|---|
| Attach IAM instance role `patchwork-dev-box` | All AWS work | [`plan/09 §1.1`](../plan/09-aws-infra-and-cost.md#11-attach-an-iam-role-to-this-ec2-instance); policy file `infra/iam/patchwork-iam-scoped.json` | ⏭ owner |
| Budget alert email address(es) | Budget alerts | Tell me which address(es) to use | ⏭ owner |
| Enable Bedrock Claude model access (ap-south-1) | Phase 5a | Bedrock console → Model access | ⏭ owner |
| Activate the `Project` cost-allocation tag / Cost Explorer | Cost report by tag | Billing console (payer account) | ⏭ owner |

## Deviations from the proposal (summary)

See [`plan/02-requirements.md §4`](../plan/02-requirements.md#4-what-changed-from-the-proposal-and-why). The main one: **synthetic survey passes over the real corridor geometry replace physical drives and tape measurements**. This gives exact ground truth for area, location and repair status.

## Session log

| Date | Session summary |
|---|---|
| 2026-10-12 | Read the proposal; agreed on region (ap-south-1), budget ($300/month), access (instance role), data (open + synthetic); wrote all docs; Phase 0: repo, env, OpenCV 5 smoke test (4/4), AWS CLI + Terraform, bootstrap IaC, cost-report automation |
