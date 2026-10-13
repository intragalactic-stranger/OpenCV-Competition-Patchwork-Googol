# 11: Decisions and risks

## Decision log

| ID | Date | Decision | Why | Alternatives rejected |
|---|---|---|---|---|
| D-01 | 2026-10-12 | **No real capture; open data + synthetic generator** | Owner's choice; exact ground truth is better for evaluation | Real drives (not available) |
| D-02 | 2026-10-12 | Region **ap-south-1**, budget **$300/month** | Data locality (Mumbai); AgentCore, Bedrock, Batch, Aurora and Location all available | us-east-1 |
| D-03 | 2026-10-12 | Dev-box access via **IAM instance role** (`PowerUserAccess` + IAM scoped to `patchwork-*`) | No long-lived keys on disk | Access keys |
| D-04 | 2026-10-12 | **Midpoint-first** delivery: P0–P4 (+5a) before anything else | The second part of the grant depends on a credible halfway demo | Building in strict proposal order |
| D-05 | 2026-10-12 | **No NAT gateway**; Lambdas outside the VPC use the Aurora **Data API**; Batch in public subnets | A NAT costs about $33+/month idle, more than all compute | NAT; interface endpoints (~$7/month each) |
| D-06 | 2026-10-12 | Synthetic world uses **real OSM geometry** of the proposal's corridor | Keeps localisation, snapping and context real | A fictional city |
| D-07 | 2026-10-12 | Segmentation: **SegFormer-B0** as proposed for the competition. A **licence-clean fallback** (LR-ASPP/DeepLabV3 MobileNetV3, BSD) is trained too if the release licence matters. | `mit-b0` weights are under NVIDIA's research licence, which conflicts with an Apache-2.0 weight release | Release SegFormer weights under Apache (not allowed) |
| D-08 | (Phase 3) | ONNX engine: `ENGINE_NEW` primary; deviations recorded here | Proposal claim | — |
| D-09 | 2026-10-12 | `file_complaint` targets a **mock endpoint** | Never send fabricated complaints to a real authority | Real BMC portal |
| D-10 | 2026-10-12 | Python **3.12** via uv (system has 3.14) | Wheel availability for OpenCV 5, PyTorch, SageMaker SDK | 3.14 |
| D-11 | 2026-10-12 | Terraform (not CDK) | Owner's existing skill set; plain state | CDK, SAM |
| D-12 | 2026-10-12 | Synthetic video rendered at **15 fps** (proposal: 60) | At 70 km/h that is still 5 frames per 4 m, and triage keeps about one per 4 m. Renders 4× faster than 60 fps. | 30/60 fps |
| D-13 | 2026-10-12 | Dev box is in **us-east-1**; all project resources stay in **ap-south-1**. Full-corridor synthetic passes are **rendered on Batch in ap-south-1**, so we don't pay cross-region transfer for multi-GB clips. Small demo clips may be uploaded from the dev box. | Cross-region transfer costs about $0.02/GB | Moving the dev box |
| D-14 | 2026-10-12 | Terraform remote state uses **S3 native locking** (`use_lockfile`, Terraform ≥ 1.10); no DynamoDB lock table | One less resource | DynamoDB lock table |
| D-15 | 2026-10-12 | Pin **`opencv-contrib-python-headless==5.0.0.93`**; the fallback engine order is `ENGINE_NEW → ENGINE_ORT → ENGINE_CLASSIC` | Verified in the Phase 0 smoke test | — |
| D-16 | 2026-10-12 | Budget alert emails are a **required Terraform variable** (in git-ignored `terraform.tfvars`), not hard-coded | Owner chooses the recipients | — |
| D-17 | 2026-10-12 | LLMs are **Amazon Nova** models on Bedrock (not Anthropic) for the agent and the VLM fallback | Owner's choice | Claude on Bedrock |
| D-18 | 2026-10-12 | **Permissions boundary** `patchwork-boundary` is mandatory on every `patchwork-*` role; the dev-box role is read-only to itself | Closes the self-escalation path in the IAM-scoped policy (a role that can attach policies could grant itself admin) | Trusting the scoped policy alone |
| D-19 | 2026-10-12 | The renderer draws the road in **road-aligned coordinates** (each view is locally straight); curvature lives in the corridor polyline used for GNSS, lat/lon and chainage | The image geometry is then *exactly* the camera's road-plane homography, so measurement ground truth is exact; curves don't affect area measurement | Full 3D curved-road rendering |
| D-20 | 2026-10-12 | Survey loop = **28.6 km** routed on OSM through named-road waypoints: Coastal Road driven once (10.1 km control, of which 3.1 km tunnel); return via Worli Seaface → Haji Ali → Warden Rd → Kemps Corner → Marine Drive | Matches the proposal's corridor; the control section is driven once per pass | Hand-drawn route |
| D-21 | 2026-10-12 | GNSS/IMU written as **CSV** (`gnss.csv`, `imu.csv`) instead of GPX | Simpler and lossless (HDOP, fix flag, NaN in tunnels) | GPX |
| D-22 | 2026-10-12 | Camera model lives in `patchwork/camera.py`, **shared** by the renderer and perception | One definition of geometry on both sides | Separate copies |
| D-23 | 2026-10-13 | Triage target restated fps-independently: **≤ 620 kept frames/km with ≤ 2% recall loss** (the proposal's 8–12% of 60 fps frames at 42 km/h). Spacing 3 m so every defect is in ≥ 2 kept frames | Our video is 15 fps (D-12); a percentage of frames is meaningless across frame rates | Keep "8–12%" (would mean 1 frame per 0.5 m at 15 fps) |
| D-24 | 2026-10-13 | Real segmentation masks from **Pothole Mix v2** (4,340 pairs, CC BY-NC 3.0; sources keep their own licences). Weights trained on it are **research / non-commercial**. Indian Roads (e-Yantra) not used: GPL-2.0 and only 230 pothole images | Largest openly downloadable pothole-mask set, with no account needed; the competition entry is research | Indian Roads via Kaggle (account + GPL); Roboflow sets (account + mixed provenance) |
| D-25 | 2026-10-13 | **Training on CPU only** (owner's instruction): AWS Batch on Graviton Spot, 32 vCPU, CPU-only PyTorch wheels. No SageMaker GPU | Cost; SegFormer-B0 is small (3.7 M params). The GPU quota for this new account is also 0 | SageMaker `ml.g5.xlarge` Spot (quota requested, unused) |
| D-26 | 2026-10-13 | Heavy data steps (rendering, dataset preparation, training) run **on Batch, S3 to S3**; the dev box only orchestrates | The dev box has a 48 GB disk; rendering is 3× faster on Graviton (77 ms/frame) | Bigger dev box |
| D-27 | 2026-10-13 | **Zero real spend: everything runs on AWS promotional credits** (owner's instruction). Only first-party AWS services. **Banned** because promotional credits typically exclude them: AWS Marketplace (incl. third-party models on Bedrock), Route 53 domain registration, Savings Plans / Reserved Instances upfront, paid Support plans. A `patchwork-real-spend` budget measures cost *after* credits and alerts at $0.01 | The owner pays nothing out of pocket; credits verified to cover EC2, EBS, VPC, S3 and Bedrock (Sep–Oct usage 100% offset) | Gross $300 budget only (would not notice an uncovered charge) |
| D-28 | 2026-10-13 | Approval task token stored **in Aurora** (`approval_request`, additive schema v1.1), written by Step Functions through its RDS Data API integration; no DynamoDB, no Lambda in the approval path | One fewer service; the token never passes through the agent or any tool the agent can call | DynamoDB table + Lambda |
| D-29 | 2026-10-13 | Pipeline split into **perceive** (per clip, parallel array job) and **assemble** (per pass, sequential: localisation needs the previous clip's end, because the loop retraces part of Marine Drive) | Full parallelism for the heavy part; correct anchoring for the cheap part | Per-clip only (wrong anchoring on retraced roads) |
| D-30 | 2026-10-13 | Segmentation input = road strip rows 448–896 at 0.75× (1440×336), defined once in `perception/segment.py` and used by training and inference | At 0.5× synthetic potholes were ~8 px tall and the model could not learn them (val IoU 0.02) | Full frame at 0.5× (first run, stopped) |

## Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R-01 | **Synthetic → real domain gap**: the model looks great on synthetic data, poor on real | High | High | Train on a mix with real Indian Roads masks; always report real-val mIoU separately; composites with real cut-outs | Claude |
| R-02 | OpenCV 5 `ENGINE_NEW` fails on a SegFormer op | Medium | Medium | Parity test in P0 (tiny model) and P3; opset/graph simplification (onnxsim); fallback chain (§06 [5]) | Claude |
| R-03 | OpenCV 5 Python wheel missing for our platform or Python version | Low | High | Python 3.12; build from source in the container if needed (about 30 min, cached in ECR) | Claude |
| R-04 | AWS permissions or Bedrock model access delays | Medium | Medium | Everything runs locally first (P1–P3 need only SageMaker; P3 can train on CPU at reduced scale) | User |
| R-05 | Cost overrun | Low | Medium | Budgets, no NAT, Spot, auto-pause, teardown targets, weekly cost report | Claude |
| R-06 | Real-mask datasets are non-commercial (Pothole Mix CC BY-NC; Indian Roads GPL) | Realised | Medium | D-24: research-licence weights; licence-clean LR-ASPP model trained on synthetic data only; never redistribute raw images | Claude |
| R-07 | Cost-allocation tag takes 24 h; Cost Explorer needs payer access | Medium | Low (report delay) | Activate in P0; fallback to the service-level account view | User |
| R-08 | Rendering a 25 km pass is slow on 4 vCPU | Medium | Low | Sub-route segments for iteration; Batch array jobs for full passes | Claude |
| R-09 | AgentCore/Strands API changes | Low | Medium | Thin adapter; tools are plain Lambdas usable without AgentCore | Claude |
| R-10 | Synthetic data judged "too easy" by reviewers | Medium | Medium | Distractor zoo (D4), photometric degradations, real-image validation numbers shown next to synthetic ones | Claude |
