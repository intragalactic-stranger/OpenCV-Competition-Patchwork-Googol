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
<!-- METRICS:END -->

<!-- FINAL-RESULTS-COMMENTARY -->

## 3. Cost

<!-- FINAL-COST -->

## 4. What is not done, and known limits

<!-- FINAL-LIMITS -->

## 5. Reproduce

Local (no AWS needed), verified on a fresh clone:

```bash
make setup && make check && make smoke
uv run python scripts/setup_world.py                     # corridor from OpenStreetMap + camera calibration
uv run python -m patchwork.synth --seed 7 --passes 1 --segment "Khan Abdul Gaffar Khan Marg" --max-m 2000
uv run python -m eval.metrics.area --oracle data/synth/seed07/pass_1
```

On AWS: `infra/terraform/bootstrap`, then `infra/terraform/envs/dev` (`terraform apply`); upload a pass with `scripts/aws/upload_pass.py`; plan repairs with `make agent-demo`; decide with `scripts/approve.py`; run the agent suite with `make scenarios`; remove everything with `make teardown`. The approval console is deployed with `terraform apply -var enable_console=true` (decision D-34).

