# Next steps: the second half

> What is built after the checkpoint, and what the remaining grant pays for.

## 1. Second-half deliverables

| Phase | Deliverable | Why it matters for the competition |
|---|---|---|
| 5b | **Full agent**: 10 tools (context lookup, duplicate-ticket check, filing via approval only, re-inspection scheduling, repair verification), confidence floor, failure handling, memory | The Agentic Vision path is scored on task success, failure handling and human control |
| 6 | **Repair verification across passes**: GNSS gate → ORB + homography → mask comparison → unchanged/repaired/degraded/new; VLM context attributes in OpenCV 5 | "Verification creates accountability", the core idea of the proposal |
| 7 | **Web console**: upload, map, defect history, approve/reject, before/after; CloudWatch dashboard with **human override rate** on the front page | The live judged demo |
| 8 | **Full evaluation**: 40 scripted agent scenarios in CI (including adversarial), baselines and ablations table, RDD2022 external check | "Metrics checked, not asserted" |
| 9 | **Hardening and release**: teardown/fresh deploy, recorded demo, Apache-2.0 code, CC-BY labels, scenario suite | Reusable public outputs |

## 2. What the remaining grant pays for

| Item | Estimate | Note |
|---|---|---|
| Additional SageMaker GPU training (label iteration, licence-clean model, severity calibration) | $30–60 | Spot, max-runtime capped |
| Bedrock + AgentCore for agent development and the **40-scenario regression suite on every change** | $40–90 | The largest second-half cost; runs repeatedly, not once |
| Processing 5+ more synthetic passes (D3 to 8 passes) + the false-positive zoo | $5–15 | Batch Graviton Spot |
| Aurora, S3, API, CloudFront, Location, CloudWatch for 6 more weeks | $40–80 | Auto-pause keeps this low |
| **Total second half (estimate)** | **≈ $115–245** | Refined from the actual first-half cost report |

## 3. Risks carried into the second half

| Risk | Plan |
|---|---|
| Synthetic-to-real gap in segmentation | Report real-image metrics separately; add composites; licence-permitting, more real data |
| Re-ID F1 below 0.90 | ORB on the surrounding texture (not the defect), plus chainage consistency; report the GNSS-only ablation honestly |
| Agent regressions | Scenario suite in CI with recorded responses; hard gate on ungrounded IDs |

## 4. Milestones after the checkpoint

[[TBD: dates relative to the checkpoint date]]
| Milestone | Target date |
|---|---|
| Full agent + 20 scenarios | checkpoint + 1.5 weeks |
| Repair verification metrics on D3 | checkpoint + 2.5 weeks |
| Console + dashboard | checkpoint + 3.5 weeks |
| Full evaluation table + CI | checkpoint + 4.5 weeks |
| Release + submission | checkpoint + 5.5 weeks |
