# Next steps: the second half

> What is built after the checkpoint, and what the remaining grant pays for.

## 1. Second-half deliverables

| Phase | Deliverable | Why it matters for the competition |
|---|---|---|
| 5b | **Agent on AgentCore**: move the 5 working tools behind AgentCore Gateway (Lambda) and host the Strands agent on AgentCore Runtime; then the **full agent**: 10 tools (context lookup, duplicate-ticket check, filing via approval only, re-inspection scheduling, repair verification), confidence floor, failure handling, memory | The Agentic Vision path is scored on task success, failure handling and human control |
| 6 | **Repair verification across passes**: GNSS gate → ORB + homography → mask comparison → unchanged/repaired/degraded/new; VLM context attributes in OpenCV 5 | "Verification creates accountability", the core idea of the proposal |
| 7 | **Web console**: upload, map, defect history, approve/reject, before/after; CloudWatch dashboard with **human override rate** on the front page | The live judged demo |
| 8 | **Full evaluation**: 40 scripted agent scenarios in CI (including adversarial), baselines and ablations table, RDD2022 external check | "Metrics checked, not asserted" |
| 9 | **Hardening and release**: teardown/fresh deploy, recorded demo, Apache-2.0 code, CC-BY labels, scenario suite | Reusable public outputs |

## 2. What the remaining grant pays for

All AWS usage is paid by **promotional credits**, and real money paid stays at $0.00 (decision D-27, enforced by the `patchwork-real-spend` budget and the per-service coverage table in the cost report). The figures below are credit consumption.

| Item | Estimate (credits) | Note |
|---|---|---|
| CPU training runs on Batch Graviton Spot (licence-clean model, severity calibration, more real data) | $5–15 | About $1–2 per run (c7g.8xlarge Spot, a few hours); no GPU (D-25) |
| Amazon Nova + AgentCore: agent development and the **40-scenario regression suite on every change** | $30–80 | Largest second-half item; about $0.02–0.05 per agent run today |
| Processing more synthetic passes (D3 to 8 passes) + the false-positive zoo | $5–15 | Batch Graviton Spot, parallel per clip |
| Aurora (auto-pause), S3, CloudFront, Location, CloudWatch, Step Functions for 6 more weeks | $30–70 | Scale-to-zero everywhere |
| **Total second half (estimate)** | **≈ $70–180 of credits** | Refined from the actual first-half cost report ([02](02-COST-REPORT.md)) |

## 3. Risks carried into the second half

| Risk | Plan |
|---|---|
| False positives on shadows and wet patches (10/km at the midpoint; target 0.5) | Hard-negative fine-tune from the training world; temporal/shape check before a detection enters the register; measured on the Coastal Road control section |
| Large shallow depressions under-measured (end-to-end MAPE 34%) | Soft-boundary labels, larger input, mask fusion across frames; oracle-mask geometry is already at 2.1% |
| Synthetic-to-real gap in segmentation | Report real-image metrics separately; add composites; licence-permitting, more real data |
| Re-ID F1 below 0.90 | ORB on the surrounding texture (not the defect), plus chainage consistency; report the GNSS-only ablation honestly |
| Agent regressions | Scenario suite in CI with recorded responses; hard gate on ungrounded IDs |

## 4. Milestones after the checkpoint

Dates are relative to the checkpoint review.

| Milestone | Target date |
|---|---|
| Full agent + 20 scenarios | checkpoint + 1.5 weeks |
| Repair verification metrics on D3 | checkpoint + 2.5 weeks |
| Console + dashboard | checkpoint + 3.5 weeks |
| Full evaluation table + CI | checkpoint + 4.5 weeks |
| Release + submission | checkpoint + 5.5 weeks |
