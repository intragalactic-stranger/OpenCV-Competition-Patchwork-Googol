# 03: Architecture

## 1. The big picture

```
                                   ┌───────────────────────── CAPTURE (simulated) ─────────────────────────┐
                                   │  synth generator  ──►  clip.mp4 + gnss.gpx + imu.csv + truth.json        │
                                   │  (real OSM corridor, camera model, defects of known m², pass states)    │
                                   └─────────────────────────────────────┬──────────────────────────────────┘
                                                                         │  ingest: triage + YuNet/plate blur
                                                                         ▼  (unblurred frames never stored)
┌─ INGEST ───────────────────────────────────────────────────────────────────────────────────────────────────┐
│  S3 patchwork-raw (KMS, 30-day expiry)  ──ObjectCreated──►  EventBridge  ──►  SQS (+DLQ)  ──►  Step Functions │
└──────────────────────────────────────────────────────────────────────────────────────────────┬─────────────┘
                                                                                               ▼
┌─ PERCEIVE ─────────────────────────────────────────────────────────────────────────────────────────────────┐
│  AWS Batch on EC2 Graviton Spot (arm64 container, OpenCV 5)                                                 │
│   undistort → IPM homography → segment (ONNX, DNN ENGINE_NEW) → measure m² → severity → material           │
│   DynamoDB: job state + idempotency key (clip_sha256 + pipeline_version)                                   │
│  SageMaker AI training jobs (GPU Spot, then off)  ──►  model.onnx in S3 (model registry prefix)             │
└──────────────────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                               ▼
┌─ STATE ────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Aurora Serverless v2 PostgreSQL + PostGIS (defect register, Data API on)    S3 patchwork-artifacts         │
│  Amazon Location: SnapToRoads, reverse geocode, map tiles                     (crops, overlays, traces, PDFs)│
└──────────────────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                               ▼
┌─ ACT ──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Bedrock AgentCore Runtime (Strands agent, Nova on Bedrock)   ──►  AgentCore Gateway  ──►  Lambda tools    │
│  request_human_approval ──► Step Functions waitForTaskToken ◄── Console approve/reject (API Gateway)        │
│  file_complaint (only after token) ──► mock municipal webhook     schedule_reinspection ──► next pass queue │
└──────────────────────────────────────────────┬────────────────────────────────────────────────────────────┘
                                               ▼
┌─ SEE ──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Console / map viewer: S3 + CloudFront + MapLibre (Amazon Location tiles); API Gateway + Lambda              │
│  Observability: OpenTelemetry → CloudWatch (metrics, logs, dashboard) + X-Ray; AWS Budgets; Cost Explorer    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Components and responsibilities

| Component | Code | Runs on | Responsibility |
|---|---|---|---|
| Synthetic world | `src/patchwork/synth/` | dev box / Batch | Corridor from OSM, camera model, road rendering, defect lifecycle across passes, GNSS/IMU simulation, ground truth |
| Ingest stage | `src/patchwork/perception/{triage,privacy}.py` | dev box ("device") / Batch | Frame selection, face and plate blur, upload of a blurred clip plus keyframes |
| Perception | `src/patchwork/perception/` | Batch (arm64) | Calibration, undistortion, IPM, segmentation (OpenCV 5 DNN), measurement, severity, material |
| Register | `src/patchwork/register/` | Batch / Lambda | PostGIS writes, dedup, road snapping, cross-pass matching queries |
| Pipeline runner | `src/patchwork/pipeline/` | Batch | Stage orchestration inside a job, idempotency, metrics emission |
| Agent | `src/patchwork/agent/` | AgentCore Runtime + Lambda | Reasoning loop, tools, grounding, work-order PDF, tracing |
| API / console | `src/patchwork/api/`, `console/` | Lambda, S3+CloudFront | Map, defect detail, approvals, upload |
| Training | `training/` | SageMaker | Fine-tune segmentation, export ONNX, parity check |
| Evaluation | `eval/` | dev box / CI | Metrics, scenarios, ablations, reports |
| Infra | `infra/terraform/` | — | Everything in AWS, tagged `Project=patchwork` |

## 3. The one contract between the halves

Perception and agent meet at **one artefact: the defect record schema** ([05-defect-record-schema.md](05-defect-record-schema.md)).
It is frozen at the end of Phase 1. After that, either half can slip without blocking the other: the agent can be developed against synthetic register rows, and perception can be evaluated without the agent.

## 4. Key flows

### 4.1 Process a pass (midpoint critical path)
```
synth/upload ─► S3 raw/{pass_id}/{clip_id}.mp4 (+ .gpx, .imu.csv, .meta.json)
   ─► EventBridge rule (suffix .meta.json, written last so the clip is complete)
   ─► SQS ─► EventBridge Pipe ─► Step Functions "process-clip"
         1. Check idempotency (DynamoDB conditional put on clip_sha256#pipeline_version)
         2. Batch SubmitJob .sync (Graviton Spot)  — retries ×3 on Spot reclaim
              perception: frames → masks → measurements → observations.parquet + crops/overlays to S3
         3. Lambda "register-load": observations → Aurora (Data API, one transaction), dedup, snap to road
         4. Lambda "match-passes" (basic at midpoint): link observations to defect tracks, set status
         5. Emit metrics (km processed, defects, stage timings, $ estimate) → CloudWatch
         6. Mark job done in DynamoDB
   on failure ─► DLQ + CloudWatch alarm
```

### 4.2 Agent proposes and a human approves
```
trigger (pass processed / console button) ─► AgentCore Runtime: "Prepare work packages for <road/area>"
  agent ─► query_defects ─► cluster_into_packages ─► estimate_materials ─► lookup_context ─► check_existing_tickets
        ─► draft_work_order (PDF to S3) ─► request_human_approval
              Lambda starts Step Functions "approval" execution: waitForTaskToken
              token stored server-side (DynamoDB), NEVER returned to the model
  human in console ─► POST /approvals/{id} {approve|reject, note} ─► SendTaskSuccess/Failure
  on approve ─► Step Functions invokes file_complaint (mock webhook) + schedule_reinspection
  on reject  ─► recorded as an override; the agent is told the outcome on its next run
```

### 4.3 Verify a repair
```
next pass processed ─► match-passes: for each open defect on the re-driven stretch
   GNSS gate (≤ 15 m) ─► ORB keypoints on rectified patches ─► RANSAC homography consistency
   ─► compare rectified masks (IoU, area delta) ─► status unchanged/repaired/degraded ; unmatched new obs ─► new
   ─► verify_repair tool: work order filed but status unchanged after re-inspection ─► escalate with before/after evidence
```

## 5. Local vs cloud

The same Python package runs in both places. Only the adapters change:

| Concern | Local (dev, tests) | AWS |
|---|---|---|
| Object storage | `./data/` via `fsspec` file:// | S3 via `fsspec` s3:// |
| Database | PostGIS in Docker (`docker/docker-compose.yml`) | Aurora Serverless v2 PostGIS via the RDS Data API |
| Orchestration | `make run-pass` (Python runner) | Step Functions + Batch |
| Agent model | Bedrock (same) or recorded responses for tests | Bedrock via AgentCore |
| Approval | CLI prompt / local endpoint | Step Functions task token + console |

Configuration lives in a single `PATCHWORK_ENV=local|aws` setting plus `config/*.yaml`.

## 6. Networking decision (cost-driven)

- **No NAT gateway.** A NAT gateway costs about $33+/month idle, more than all our compute.
- Lambdas run **outside a VPC** and reach Aurora through the **RDS Data API** (HTTPS, IAM-authenticated).
- Batch compute runs in **public subnets with a public IP** and a security group with no inbound rules. It reaches S3, DynamoDB and the Data API over HTTPS. An S3 gateway endpoint (free) keeps S3 traffic private.
- Aurora sits in **private subnets** with no public access. The only way in is the Data API (plus a temporary SSM-tunnel bastion pattern for admin, if ever needed).

## 7. Technology choices

| Area | Choice | Notes |
|---|---|---|
| Language | Python 3.12 (uv) | OpenCV 5 wheels and SageMaker/Strands compatibility |
| Vision | OpenCV 5 (`opencv-contrib-python` 5.x) | ArUco/ChArUco, calib, DNN `ENGINE_NEW`, YuNet, ORB |
| Training | PyTorch + HF `transformers` (SegFormer) on SageMaker | Export ONNX opset ≥ 17, dynamic H/W |
| Geo | PostGIS, Shapely, pyproj, OSM via `osmnx`/Overpass | Corridor geometry and road graph |
| Agent | Strands Agents SDK on Bedrock AgentCore Runtime | Tools via AgentCore Gateway → Lambda |
| LLM | **Amazon Nova** on Amazon Bedrock (APAC cross-region inference profile if needed) | Owner's choice (D-17); model ID confirmed in Phase 5a |
| PDF | `reportlab` | Work orders |
| IaC | Terraform ≥ 1.9, AWS provider 6.x | Remote state in S3 + DynamoDB lock |
| Viewer | Static HTML + MapLibre GL + Amazon Location map style | No build step at midpoint |
| Tests | pytest, moto for AWS unit tests | `make test` |
