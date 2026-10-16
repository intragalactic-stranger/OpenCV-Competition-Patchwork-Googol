# Patchwork: final report

**OpenCV AI Competition 2026 · Agentic Vision track · Team Googol · Author: Ganeshan Arumuganainar**

> Patchwork turns ordinary dashcam video into a measured, map-linked register of road defects. For every pothole, broken road edge or sunken patch it records where it is, **how many square metres are damaged**, how serious it is and how much asphalt the repair needs, and on the next drive **whether it was actually repaired**. An AI assistant on Amazon Nova turns the register into work packages and work orders; **a human approves each one before anything is filed.**

Every number below is computed by code from the pipeline's outputs and the synthetic ground truth; the results table is written by `uv run python -m eval.report`. The midpoint checkpoint pack is kept unchanged in [`midpoint/`](midpoint/) for comparison.

## 1. What was built

```
dashcam video + GPS ─► S3 ─► EventBridge ─► Step Functions ─► AWS Batch (Graviton Spot, OpenCV 5 container)
   triage → face/plate blur → calibration + undistortion → bird's-eye view (1 cm/px)
   → SegFormer-B2 in OpenCV 5 DNN ENGINE_NEW → m², severity, material → localisation → cross-pass matching
                              │
            Aurora Serverless v2 + PostGIS (defect register; one database per survey)
               │                                         │
   CloudFront map (MapLibre + Amazon Location)    Agent: Strands + Amazon Nova Pro (9 grounded tools)
                                                  → request approval (Step Functions task token)
                                                  → human approves (CLI, or the console) → mock ticket
                                                  → next survey pass → verify_repair → verified / escalated
   Training: SageMaker GPU (NVIDIA A10G) → ONNX → OpenCV 5 evaluation on Graviton (Batch)
```

| Part | What it does | Where |
|---|---|---|
| Synthetic survey | Real OpenStreetMap geometry of a 28.6 km Mumbai loop; a simulated dashcam with lens distortion, GNSS/IMU noise, look-alikes (shadows, wet patches, manholes, seams, old patches); defects with exact area that are repaired, degrade or appear between passes | `src/patchwork/synth/` |
| OpenCV 5 perception | ChArUco calibration, undistortion folded into one `remap`, road-plane homography to a 1 cm/px bird's-eye view, pitch from lane lines, frame triage with road-plane optical flow, YuNet face blur and plate blur, segmentation in the new DNN engine, metric measurement fused over frames | `src/patchwork/perception/` |
| Segmentation model | SegFormer-B2 trained on GPU (SageMaker) on real pothole photos (Pothole Mix) plus synthetic frames and look-alike negatives; exported to ONNX and scored through OpenCV 5 | `training/`, [model card](midpoint/07-MODEL-CARD.md) |
| Cloud pipeline | Upload → EventBridge → Step Functions → Batch (one container per clip, in parallel) → register → map; failure alarms by email | `infra/terraform/`, `src/patchwork/pipeline/` |
| Register and verification | PostGIS register; matcher v2 links a detection to a known defect by chainage, lateral offset and area, one-to-one; a defect the next pass drives past without seeing is marked repaired ("not seen again") | `src/patchwork/register/` |
| Agent | Ward Engineer's Assistant on Amazon Nova Pro: query, context (schools/hospitals/bus stops), existing-work check, clustering with a deterministic exposure score, materials, work order, approval request, re-inspection, repair verification. Every ID is validated by the tools and by a database trigger; the final answer is checked for unknown IDs | `src/patchwork/agent/` |
| Human gate | Step Functions waits on a task token stored in the database, never shown to the model; approve files a **mock** ticket, reject records an override | `scripts/approve.py`, `viewer/console.html` |
| Evaluation | Metrics against ground truth, a no-rectification ablation, matcher v1 vs v2, run A/B, 40 live agent scenarios, CI on every push | `eval/`, `.github/workflows/ci.yml` |


## 2. Results

<!-- METRICS:BEGIN -->
| Metric | Target | Result | Status |
|---|---|---|---|
| Detection recall (held-out world, D1) | ≥ 0.85 | 0.99 · 248/251 visible defects over 56.8 km; 2.76 FP/km overall | ✅ |
| False positives per km, Coastal Road control section (D2) | ≤ 0.5 | 0.25 · 5 FPs over 20.2 km | ✅ |
| Damaged-area MAPE, end to end (model masks) | ≤ 20% | 13.9% · n=239 measured defects; see assets/area_scatter.png | ✅ |
| Damaged-area MAPE, oracle masks (geometry only, estimated pitch) | ≤ 5% | 2.14% · n=18 defects; median 2.16%, p90 4.42%; true-pose 1.4%, nominal-pitch 4.44% | ✅ |
| Median localisation error | ≤ 8 m | 2.63 m · p90 6.51 m; raw GNSS median 6.23 m; tunnel (no GNSS) median 7.49 m; 37520 frames | ✅ |
| Segmentation IoU (damage), real photos (test split) | reported (aim ≥ 0.55) | 0.722 · segformer nvidia/mit-b2 in OpenCV ENGINE_NEW; see MODEL-CARD | ✅ |
| Segmentation IoU (damage), synthetic held-out stretch | reported (aim ≥ 0.75) | 0.747 · segformer nvidia/mit-b2 in OpenCV ENGINE_NEW; see MODEL-CARD | ❌ |
| ONNX parity: OpenCV 5 ENGINE_NEW vs onnxruntime (trained SegFormer-B2) | ≤ 1e-3 | 3.2e-05 · 50 images; 100.000% same pixel decisions; ENGINE_CLASSIC cannot load it | ✅ |
| Frame triage: kept frames per km (recall loss) | ≤ 620/km, ≤ 2% loss | 284/km, 0.0% loss · 21.63% of 15 fps frames; 98.9% of defects in ≥ 2 kept frames; odometry -0.6% over 28.558 km | ✅ |
| Processing time per km (Batch, Graviton, 4 vCPU per clip) | reported | 9.7 vCPU-container-min/km · clips run in parallel: wall-clock per pass ≈ time of the slowest clip | ℹ️ |
| Cost per km processed (perception compute, Graviton Spot) | < $0.02 | $0.0083 · 580 s × 4 vCPU per km at $0.01286/vCPU-h; seg-v4 (SegFormer-B2); midpoint model: $0.0021/km | ✅ |
| Cross-pass re-ID F1 (matcher v2: chainage + lateral offset + area, one-to-one) | ≥ 0.90 | 0.80 · precision 0.695, recall 0.933; v1 rule on the same detections 0.77; repaired defects reported 'not seen again': 58% of 33; still-present defects wrongly reported gone: 6 of 106 | ❌ |
| Run A/B: plan changes with measured area (agent on Amazon Nova) | must change | changed · 0.20 → 3.10 m²: priority 3 → 1, hot-mix 0.0252 → 0.4007 t; register source: pipeline output; see assets/ablation_ab.md | ✅ |
| Ablation: area without the bird's-eye view (same true masks, one fixed m²/pixel) | worse than with it | 46.9% MAPE · vs 2.14% with OpenCV rectification; bias -45% (distant damage shrinks in the image); n=20 | ℹ️ |
| Repair verification on filed work orders (verify_repair after the next pass) | correct verdicts | 8/8 correct · 6 filed packages → verified 2, escalated 1, still open 3; checked against truth | ✅ |
| Idempotency: re-loading a processed pass | 0 new rows | 0 new observations, 0 new defects · 216 tracks re-loaded | ✅ |
| Agent scenarios, live on Amazon Nova (planning, questions, adversarial, verification) | 0 ungrounded IDs (hard gate) | 39/40 passed · answers citing an unknown ID: 0; by category adversarial 12/12, existing_work 3/3, information 7/8, low_confidence 2/2, planning 12/12, verification 3/3; see eval/results/agent_scenarios.json | ✅ |

_Generated 2026-10-16 03:39 UTC by `uv run python -m eval.report`._
<!-- METRICS:END -->

### 2.1 Midpoint → final, same held-out survey (world seed 11, 2 passes, 56.8 km)

| | Midpoint (seg-v3, SegFormer-B0, CPU) | Final (seg-v4, SegFormer-B2, GPU) |
|---|---|---|
| Defects found (recall) | 0.94 (236/251) | **0.99 (248/251)** |
| Area error, full system (MAPE) | 27.8% ❌ | **13.9% ✅** (median 7.9%) |
| False alarms, control road | 0.30 /km | **0.25 /km** |
| False alarms, whole survey | 3.1 /km | **2.8 /km** |
| IoU on real photos (test) | 0.50 | **0.72** |
| Same defect recognised next pass (F1) | 0.73 (matcher v1) | **0.80** (matcher v2; v1 on the same detections: 0.77) |
| Processing cost | $0.0021 /km | $0.0083 /km (still < $0.02) |

The model change did most of the work: same training data, a larger encoder trained on a GPU for one hour. Area error halved and now meets the proposal's 20% target, which the midpoint missed.

### 2.2 The closed loop, run on AWS

1. **Pass 1** uploaded → Step Functions → 10 Batch containers in parallel → 216 defects in the register and on the map (45 min).
2. **Agent** (Amazon Nova Pro): "Plan repairs for Khan Abdul Gaffar Khan Marg" → 21 work packages, materials and work orders, an approval request for each, re-inspections for the low-confidence ones; the answer cites all 21 packages once and no unknown ID.
3. **Engineer** approved 6 packages (mock tickets filed by Step Functions) and rejected 1 ("not measured: re-inspect first").
4. **Pass 2** uploaded → 141 detections linked to known defects, 48 new, 75 known defects not seen again (→ `repaired`).
5. **Agent verifies** the 6 filed packages: 2 `verified`, 1 `escalated` (partly repaired), 3 still open. Checked against the ground truth, the verdict is right for **8 of 8** real defects; one "verified" package contained a single false detection, so there was nothing real to repair.
6. **Re-loading** a processed pass adds 0 rows (idempotent).

### 2.3 Where the targets are still missed, and why

- **Re-identification F1 0.80 (target 0.90).** Matching itself is precise: 54 of the 56 wrong links at the midpoint involved a false detection on one side. The remaining errors come from look-alikes detected on both passes (manhole covers, old patches), which no matcher can fix; fewer false detections can.
- **Repaired defects reported "not seen again": 58%.** A fresh repair patch is sometimes still segmented as damage (17 detections on patches in pass 2), so the defect looks present. A patch-texture check was tried and did not separate patches from potholes, so it was not shipped.
- **Synthetic IoU 0.747 against an aim of 0.75**: just below.

### 2.4 Agent: 40 scenarios, live

Every scenario runs Amazon Nova Pro with the real tools on the final register, each inside a database transaction that is rolled back (decision D-35); CI re-scores the recorded traces on every push. Result: **39 of 40** pass and **no answer cites an ID that is not in the register** (the hard gate).

| Category | Passed | What is checked |
|---|---|---|
| Planning | 12/12 | every package the agent creates is sent for approval, or re-inspected when below the confidence floor; at most 3 approvals when the user says "at most three" |
| Read-only questions | 7/8 | the right lookup, no write; the measured area quoted correctly |
| Adversarial | 12/12 | unknown defect/package IDs rejected, no depth claims, no "filed/approved" claims after "file it yourself" or a fake SYSTEM override, out-of-range thickness refused, no invented potholes, no approval token disclosed, off-topic requests declined without tools |
| Existing work | 3/3 | a defect already in an active package is not ordered twice |
| Low confidence | 2/2 | unmeasured defects get a re-inspection |
| Verification | 3/3 | `verify_repair` on a filed package; unknown package rejected |

The one failure (B07) is a real agent mistake: asked whether a defect was measured, it answered and *also* scheduled a re-inspection nobody asked for. The first full run on this register scored 36/40; two changes fixed three of the four failures without touching the tests: `cluster_into_packages` now returns a deterministic `next_step` for each package, and the re-inspection tool states it is for planning only. The fourth failure was a wrong test (the prompt allowed at most three packages and the test demanded all of them), and was corrected.



## 3. Cost

All usage was paid from the project's AWS credits; only first-party AWS services and Amazon models were used (decision D-27).

| Period | AWS usage | Source |
|---|---|---|
| 12–15 Oct (build, midpoint, CPU training, two surveys on seg-v2/v3) | **$19.67** | AWS Cost Explorer (`make cost-report`, [midpoint/02-COST-REPORT.md](midpoint/02-COST-REPORT.md)) |
| 16 Oct (GPU training, final survey, agent evaluation) | **≈ $10** (estimate) | measured run times × list or Spot prices, below; Cost Explorer shows it within 24 h |
| **Project total** | **≈ $30** | |

Estimate for 16 Oct, line by line:

| Item | Measured | Price | ≈ Cost |
|---|---|---|---|
| SageMaker GPU training (`ml.g5.2xlarge`): trial + full run | 468 s + 3,977 s billable | $1.82/h | $2.25 |
| Batch Graviton Spot: final survey (2 passes, 10 clips each) + OpenCV evaluation of the model | 33,000 s × 4 vCPU perceive, 18 min × 32 vCPU evaluation, assembly | Spot, $0.41/h per 32 vCPU | $0.6–1.6 |
| Amazon Nova Pro: 40-scenario suite (twice), road-wide plan, verification, run A/B | ≈ 1.4 M tokens, mostly input | $0.94 / $3.76 per M | ≈ $1.4 |
| Development workstation (EC2, us-east-1) | one day | $0.15/h | ≈ $3.6 |
| Aurora Serverless v2, S3, CloudWatch, ECR, Lambda-free pipeline | | | ≈ $1 |

**Cost per km processed (perception compute):** pass 1 took **663 s of 4-vCPU Graviton Spot per km** → **$0.0095/km** (target < $0.02). The midpoint model needed 147 s/km ($0.0021/km); SegFormer-B2 is slower on CPU but much more accurate, and stays under the target.


## 4. What is not done, and known limits

Stated plainly, so nobody has to find it:

| Item | Status |
|---|---|
| **Real-world capture** | None. The surveys are simulated on real OpenStreetMap geometry; the model learns from real pothole photos (Pothole Mix). Results on real dashcam video are not measured (decision D-01). |
| **Repair verification** | "Repaired" means *not seen again* on a later pass that drove past. A repair patch that the model still detects as damage is reported as still present. An appearance check (patch texture) was tried on the midpoint survey and did not separate patches from potholes, so it was not built. |
| **Approval console** | Built (Cognito sign-in → HTTP API → Lambda, `viewer/console.html`) but **not deployed**: it creates a public sign-in page, so the owner switches it on (`enable_console = true`, D-34). The same approvals work through `scripts/approve.py`. |
| **AgentCore** | Not used. The agent runs with Strands + Amazon Nova from the development machine; its tools are plain Python over the Aurora Data API and would move behind AgentCore Gateway unchanged. |
| **VLM attributes** | Not built. Context comes from rules and OpenStreetMap points of interest. |
| **Passes** | 2 passes evaluated (pass 3 is rendered); the plan's 8 passes were not generated. |
| **Model weights** | Not released (research-only training data and encoder licence); see [DATA-LICENSES.md](DATA-LICENSES.md). |
| **Teardown** | `make teardown` is written, not run on this account. |
| **Tickets** | Every filed ticket is a mock (`MOCK-…`). Nothing is sent to any authority. |


## 5. Reproduce

Local (no AWS needed), verified on a fresh clone:

```bash
make setup && make check && make smoke
uv run python scripts/setup_world.py                     # corridor from OpenStreetMap + camera calibration
uv run python -m patchwork.synth --seed 7 --passes 1 --segment "Khan Abdul Gaffar Khan Marg" --max-m 2000
uv run python -m eval.metrics.area --oracle data/synth/seed07/pass_1
```

On AWS: `infra/terraform/bootstrap`, then `infra/terraform/envs/dev` (`terraform apply`); upload a pass with `scripts/aws/upload_pass.py`; plan repairs with `make agent-demo`; decide with `scripts/approve.py`; run the agent suite with `make scenarios`; remove everything with `make teardown`. The approval console is deployed with `terraform apply -var enable_console=true` (decision D-34).

