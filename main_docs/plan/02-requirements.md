# 02: Requirements: what "working" means

## 1. Functional requirements

### Perception (OpenCV 5)
| ID | Requirement | Phase |
|---|---|---|
| F-P1 | Ingest a video clip (MP4, 1920×1080, 30/60 fps) plus a GNSS track (1 Hz) and IMU (100 Hz) as sidecar files | 1–2 |
| F-P2 | Camera calibration from ChArUco views; store intrinsics and distortion as a versioned `calibration_id` | 2 |
| F-P3 | Frame triage keeps 8–12% of frames, using road-ROI variance, edge energy, optical flow and IMU (drop stopped or crawling frames) | 2 |
| F-P4 | Privacy: faces (YuNet) and number plates blurred **before** any frame is stored or uploaded. Unblurred frames never persist. | 2 |
| F-P5 | Undistortion + a single road-plane homography (from mounting height and pitch, checked against lane width) → bird's-eye view at a fixed cm/px | 2 |
| F-P6 | Pothole / edge-break / depression segmentation by an ONNX model running in OpenCV 5 DNN `ENGINE_NEW` | 3 |
| F-P7 | Damaged area in m², with an uncertainty estimate, measured on the bird's-eye view | 2–3 |
| F-P8 | Severity band (low / medium / high) and material estimate (area × stated patch thickness) | 3 |
| F-P9 | Defects without a valid calibration are recorded as `detected_not_measured` and excluded from work orders | 2 |
| F-P10 | Standing water or specular glare → `obscured`, re-queued for the next pass | 6 |
| F-P11 | Context attributes per defect (wheel path vs shoulder, water pooling, near a bus stop, previous patch) via the OpenCV 5 VLM, with a Bedrock fallback | 6 |

### Register
| ID | Requirement | Phase |
|---|---|---|
| F-R1 | Every observation is stored with position, chainage on a named road segment, area, severity, model and calibration versions | 4 |
| F-R2 | Spatial dedup: observations within the same pass and the same track merge into one defect | 4 |
| F-R3 | Road snapping: position → road segment + chainage (Amazon Location SnapToRoads, with a PostGIS/OSM fallback) | 4 |
| F-R4 | Idempotent processing: a re-run of a clip (for example after a Spot interruption) never duplicates rows | 4 |

### Verification
| ID | Requirement | Phase |
|---|---|---|
| F-V1 | Cross-pass matching: GNSS gate → ORB + homography consistency → comparison of rectified patches | 6 (basic at midpoint, if time allows) |
| F-V2 | Every known defect resolves to exactly one of **unchanged / repaired / degraded / new** per pass | 6 |

### Agent (Ward Engineer's Assistant)
| ID | Requirement | Phase |
|---|---|---|
| F-A1 | Tools: `query_defects`, `cluster_into_packages`, `estimate_materials`, `lookup_context`, `check_existing_tickets`, `draft_work_order`, `request_human_approval`, `file_complaint`, `schedule_reinspection`, `verify_repair` | 5 (5 tools at midpoint) |
| F-A2 | **Grounding at the tool boundary**: any defect ID that is not in the register is rejected by the Lambda | 5 |
| F-A3 | **Approval gate**: `file_complaint` and notifications need a Step Functions task token that only a human action can complete | 5 |
| F-A4 | **Confidence floor**: below it, the agent presents options instead of acting, and says so in the work order | 5 |
| F-A5 | Work-order PDF: photo, rectified overlay, quantities, stated assumptions (area not depth) and rationale | 5 |
| F-A6 | Full trace per run (tool calls, arguments, latencies, tokens, defect IDs touched) → S3 + CloudWatch via OpenTelemetry | 5 |
| F-A7 | Failure handling: tool timeout → retry with backoff → degrade to a human decision; ambiguous road match → refuse and ask | 5 |

### Interfaces
| ID | Requirement | Phase |
|---|---|---|
| F-I1 | Midpoint: a static map viewer (defects coloured by severity, click for overlay and numbers) | 4 |
| F-I2 | Full console: upload a clip, browse the map, approve or reject work packages, see before/after pairs | 7 |
| F-I3 | Outputs: PDF work order, CSV export, one webhook (mock municipal endpoint) | 5 |

## 2. Non-functional requirements

| ID | Requirement |
|---|---|
| NF-1 | **Privacy**: no face or plate pixels persisted anywhere; raw clips expire after 30 days; afterwards only crops and overlays remain |
| NF-2 | **Cost**: under US $0.02 per km surveyed (steady state); project spend ≤ $300/month with alarms at 50/80/100% |
| NF-3 | **Reproducibility**: all infrastructure in Terraform; all data generation seeded; model, calibration and pipeline versions on every record |
| NF-4 | **Observability**: stage timings, cost per km, agent task success, escalation rate, **human override rate**, mean time to approval |
| NF-5 | **Security**: least-privilege IAM per component, KMS encryption at rest, no long-lived keys on the dev box (instance role) |
| NF-6 | **Portability**: the core Python package runs locally (PostGIS in Docker, local filesystem) and on AWS (S3, Aurora); arm64 and x86_64 |
| NF-7 | **Honesty**: every quantity states its assumptions (area, not depth). Uncertainty is reported, never hidden. |

## 3. Metric targets (from the proposal)

| Metric | Target | Measured on |
|---|---|---|
| Detection recall at ≤ 1 false positive / km | ≥ 0.85 | D1 (synthetic measured set) + real validation set |
| False positives per km on the control section | ≤ 0.5 | D2 (synthetic Coastal Road) |
| Damaged-area MAPE vs ground truth | ≤ 20% | D1 |
| Median localisation error | ≤ 8 m | D1 (ground-truth positions known exactly) |
| Cross-pass re-identification F1 | ≥ 0.90 | D3 |
| Repair-status classification accuracy | ≥ 0.90 | D3 |
| Agent task success across 40 scripted scenarios | ≥ 0.90 | Scenario suite |
| Ungrounded claims in generated work orders | **0 (hard gate)** | Scenario suite + rubric |
| Human override rate | reported, not targeted | Console logs |
| Cost per km surveyed | < $0.02 | Cost Explorer ÷ km processed |

**Extra targets of our own**, which isolate where errors come from:
- Area MAPE with **oracle masks** (ground-truth masks, our geometry) ≤ 5%. If this fails, the error is in the geometry, not the model.
- ONNX parity, OpenCV `ENGINE_NEW` vs onnxruntime: max abs diff of logits ≤ 1e-3.

## 4. What changed from the proposal, and why

| Proposal | This build | Why |
|---|---|---|
| Builder drives a 25 km loop weekly with a phone | **Synthetic dashcam passes** over the real OSM geometry of the same corridor | No capture is available. The generator gives exact ground truth. |
| 300 potholes measured with a tape (D1) | Synthetic defects with **exact** area; real masks from public datasets for appearance | A tape has ±10–15% error; synthetic ground truth has none |
| Real repairs during the monsoon patching season (D3) | Generator simulates repaired / degraded / new between passes | Repairs can't be scheduled. Here we control the sample size (well above the 15-repair minimum). |
| False-positive zoo from monsoon clips (D4) | Synthetic distractors: shadows, wet sheen, manholes, tar seams, markings, speed breakers | Same purpose, controllable mix |
| Control section = the real Coastal Road | Synthetic clean-surface segments placed on the Coastal Road geometry | Same purpose |
| Phone does triage and blur on device | Same OpenCV code as an **ingest stage** (simulating the device), run before anything is stored | No phone in the loop; the privacy guarantee is kept |
| Real filing with the municipality | **Mock endpoint** (stub Lambda + logged webhook) | We must never send fake complaints to real authorities |
| Manual 1 km tape survey baseline | Timed estimate from published survey rates; bounding-box baseline unchanged | No field work |

**What stays exactly as proposed:** OpenCV 5 as the whole perception runtime, IPM-based measurement, SegFormer-class segmentation in `ENGINE_NEW`, PostGIS register, Step Functions + Batch Graviton Spot, AgentCore agent with Lambda tools, the human approval gate, the run A/B ablation, the 40-scenario suite and the metric targets.

## 5. Explicitly out of scope (as in proposal §12)

No depth or volume reconstruction. Not the COOL path. No live driver warnings. No city-wide dataset. Not cracks, signage or lane markings (only potholes, edge breaks and depressions). No custom hardware. No real municipal system integration (PDF + CSV + one webhook).
