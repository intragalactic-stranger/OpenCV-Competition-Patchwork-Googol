# Patchwork

**A measured road-defect register built from ordinary dashcam video, with OpenCV 5 on AWS.**

OpenCV AI Competition 2026 · Agentic Vision track · Team Googol · Author: **Ganeshan Arumuganainar**

Patchwork turns ordinary dashcam video into a map of road defects. For every pothole, broken road edge or sunken patch it records where it is, **how many square metres are damaged**, how serious it is, and how much asphalt the repair needs. When the same road is driven again, Patchwork checks each defect and marks it unchanged, worse, new, or actually repaired. An AI assistant on Amazon Nova then groups the defects into repair work packages, puts the ones near schools and hospitals first, and drafts work orders. **A human engineer approves each one before anything is filed.**

**Live map:** https://d3mt6jrs1ynczo.cloudfront.net (synthetic survey data, labelled as such)

---

## How it works

```
dashcam video + GPS ──► S3 upload ──► EventBridge ──► Step Functions ──► AWS Batch (Graviton Spot, OpenCV 5 container)
                                                                          │
   frame triage → face/plate blur → calibration + undistortion → bird's-eye view (1 cm/px)
   → SegFormer segmentation in OpenCV 5 DNN ENGINE_NEW → area in m², severity, material
   → localisation (Kalman filter + map matching) → match against earlier passes
                                                                          │
                       Aurora Serverless v2 (PostgreSQL + PostGIS): the defect register
                                │                                      │
             CloudFront map viewer (MapLibre + Amazon Location)   Agent (Strands + Amazon Nova on Bedrock)
                                                                   query → cluster → estimate → draft work order
                                                                   → request approval (Step Functions task token)
                                                                   → human approves → mock ticket filed
```

| Stage | OpenCV 5 used for |
|---|---|
| Calibration | ChArUco board detection, `calibrateCamera` (RMS 0.16 px) |
| Bird's-eye view | Road-plane homography; undistortion folded into one `remap` |
| Triage | Laplacian sharpness, edge energy, Lucas–Kanade flow on the road plane (visual odometry) |
| Privacy | YuNet face detector (`FaceDetectorYN`) and a plate/text blur |
| Segmentation | SegFormer ONNX in the new DNN engine (`ENGINE_NEW`); the classic engine cannot load the model |
| Measurement | Contours and polygon area on the metric bird's-eye mask, fused over several frames |

## Results (held-out survey: 28.6 km Mumbai loop, driven twice, 56.8 km)

| Metric | Result | Target |
|---|---|---|
| Potholes found (recall) | **0.94** | ≥ 0.85 ✅ |
| False alarms on the clean control road | **0.30 per km** | ≤ 0.5 ✅ |
| Location error (median) | **2.6 m** | ≤ 8 m ✅ |
| Area error with perfect outlines (geometry only) | **2.1%** | ≤ 5% ✅ |
| OpenCV 5 `ENGINE_NEW` vs onnxruntime | **2.0e-5** max difference | ≤ 1e-3 ✅ |
| Processing cost | **$0.002 per km** | < $0.02 ✅ |
| Run A/B: the plan changes when only the measured area changes | **changed** (priority 2 → 1) | must change ✅ |
| Area error, full system | 27.8% | ≤ 20% |
| Same defect recognised on the next pass (F1) | 0.73 | ≥ 0.90 |

All numbers are computed by `eval/` and published in [`docs/midpoint/04-RESULTS-AND-OUTPUTS.md`](docs/midpoint/04-RESULTS-AND-OUTPUTS.md).

**About the data.** The survey drives are simulated on the real OpenStreetMap geometry of Mumbai's Coastal Road, Worli Sea Face, Haji Ali and Marine Drive, so every defect's true area, position and repair status is known exactly. The segmentation model also learns from real pothole photos (Pothole Mix). See [`docs/DATA-LICENSES.md`](docs/DATA-LICENSES.md).

## Quick start

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), Docker. AWS deployment additionally needs Terraform ≥ 1.10 and an AWS account.

```bash
make setup     # create .venv and install dependencies (OpenCV 5.0.0)
make check     # lint + unit tests
make smoke     # OpenCV 5 smoke test: DNN ENGINE_NEW, ChArUco, YuNet, ORB

uv run python scripts/setup_world.py   # survey loop from OpenStreetMap + ChArUco camera calibration

# render 2 km of synthetic survey with exact ground truth, then check the geometry with true masks
uv run python -m patchwork.synth --seed 7 --passes 1 --segment "Khan Abdul Gaffar Khan Marg" --max-m 2000
uv run python -m eval.metrics.area --oracle data/synth/seed07/pass_1

# full perception with a trained model (train one with training/train.py; see the model card)
uv run python -m patchwork.pipeline.runner perceive data/synth/seed07/pass_1/clip_0* --model path/to/model.onnx --out runs/local
uv run python -m patchwork.pipeline.runner assemble data/synth/seed07/pass_1 --model path/to/model.onnx --out runs/local --overlays
```

AWS: `infra/terraform/bootstrap` (state bucket and budget alarm), then `infra/terraform/envs/dev` (VPC, S3, ECR, Batch, Step Functions, Aurora, CloudFront). Every resource is tagged `Project=patchwork`; every IAM role carries the `patchwork-boundary` permissions boundary. Step-by-step: [`docs/plan/09-aws-infra-and-cost.md`](docs/plan/09-aws-infra-and-cost.md) and [`docs/midpoint/05-DEMO-GUIDE.md`](docs/midpoint/05-DEMO-GUIDE.md).

## Repository layout

```
src/patchwork/
  camera.py        camera model shared by the renderer and perception
  synth/           synthetic survey generator: OSM corridor, road renderer, defects, lifecycle, GNSS/IMU noise
  perception/      calib, triage, privacy, ipm, pose, segment, measure, localise
  pipeline/        Batch entry points (perceive / assemble), local runner, viewer publishing
  register/        Aurora Data API client, migrations, cross-pass matching
  schema/          the defect record: pydantic models + PostGIS DDL (tested to agree)
  agent/           Strands agent on Amazon Nova, grounded tools, system prompt
training/          dataset preparation, SegFormer training, ONNX export, parity check, model card
eval/              metrics, run A/B ablation, report generator
infra/terraform/   bootstrap + dev environment modules
docker/            arm64 Batch and training images
viewer/            static MapLibre map
docs/              midpoint checkpoint pack, engineering plan, licences
```

## Documentation

- [`docs/README.md`](docs/README.md): map of all documents
- [`docs/midpoint/09-REVIEWER-WALKTHROUGH.md`](docs/midpoint/09-REVIEWER-WALKTHROUGH.md): the story, in the order to show it
- [`docs/midpoint/07-MODEL-CARD.md`](docs/midpoint/07-MODEL-CARD.md): the segmentation model
- [`docs/midpoint/08-SERVICE-MAPPINGS.md`](docs/midpoint/08-SERVICE-MAPPINGS.md): every AWS service, what it does and what it cost
- [`docs/plan/`](docs/plan/): architecture, data strategy, schema, perception, agent design, evaluation plan, decision log

## Licence

Code: Apache-2.0 ([`LICENSE`](LICENSE)). The trained SegFormer weights are **not** included and are research-only because of their training data and pretrained encoder; see [`docs/DATA-LICENSES.md`](docs/DATA-LICENSES.md). Map data © OpenStreetMap contributors (ODbL).
