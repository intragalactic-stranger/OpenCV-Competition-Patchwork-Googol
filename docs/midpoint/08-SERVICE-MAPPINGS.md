# Service mappings: which AWS service does what, and what it cost

> **One page for the reviewer.** It follows the system step by step, from raw data to a filed work order. For each step it gives the AWS service, its purpose, its resource name and the credits it consumed.
> **Billing rule:** everything is paid by **AWS promotional credits**, and real money paid is **$0.00** (decision D-27).
> **Figures** come from AWS Cost Explorer (`UnblendedCost`, record types *Usage* and *Credit*), as of **2026-10-13 12:00 UTC**. Refresh with `make cost-report`, which rewrites [02-COST-REPORT](02-COST-REPORT.md).

## 0. The money in one table

| Period | Usage (gross) | Paid by promotional credits | **Real money paid** |
|---|---|---|---|
| Project build (2026-10-12 → 13) | $4.69 | −$4.69 | **$0.00** |
| October 2026 month to date (whole account) | $12.71 | −$12.71 | **$0.00** |
| September 2026 (whole account, before the project) | $32.72 | −$32.72 | **$0.00** |

A $1 budget, `patchwork-real-spend`, watches the cost **after credits**. It emails the owner at the first cent of real spend.

> ⚠️ **Billing lag.** EC2 **Spot** usage from AWS Batch reaches Cost Explorer 24–48 h late. The Batch rows below therefore show what has been *billed so far*, plus an **estimate** from the measured job run times. These numbers will rise slightly once billing catches up, and they will still be paid by credits.

## 1. Step by step: what runs where

### Step 1 · Create the data (synthetic survey + open datasets)

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 1a | Render the synthetic dashcam survey: 2 worlds × 3 passes × 28.6 km = 60 clips with exact ground truth | **AWS Batch on EC2 Graviton Spot** (array jobs) | `patchwork-synth-render` → queue `patchwork-spot` → `patchwork-graviton-spot` | 14.7 vCPU-h ≈ **$0.19** (estimate, Spot billing lagging) |
| 1b | Store the clips, open datasets (Pothole Mix, RDD2022-India) and prepared training sets | **Amazon S3** | `patchwork-682839842398-datasets` | Included in the S3 total below |
| 1c | Container images for every job (arm64) | **Amazon ECR** | `patchwork-batch`, `patchwork-train` | **$0.0006** |

### Step 2 · Train the segmentation model (CPU only, no GPU)

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 2a | Build the training set (real + synthetic strips; hard negatives for `seg-v3`) | **AWS Batch** (4 vCPU) | `patchwork-prepare` | 1.1 vCPU-h ≈ **$0.01** (estimate) |
| 2b | Train SegFormer-B0 on CPU: 12 epochs in 3.9 h. Export ONNX, check OpenCV 5 parity, evaluate | **AWS Batch on Graviton Spot** (32 vCPU) | `patchwork-train-cpu` | 155 vCPU-h ≈ **$1.97** (estimate; includes a stopped first attempt) |
| 2c | Keep the model, checkpoints and metrics | **Amazon S3** | `…-artifacts/models/seg-v2/` | Included in S3 |

### Step 3 · A survey pass is uploaded: the pipeline starts by itself

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 3a | The uploader puts clips + GNSS/IMU into the raw bucket and writes `manifest.json` last. Ground truth is never uploaded | **Amazon S3** | `patchwork-682839842398-raw` (30-day expiry) | Included in S3 |
| 3b | `manifest.json` arriving fires an event | **Amazon EventBridge** | rule `patchwork-pass-uploaded` | **$0.000002** |
| 3c | The workflow runs: read manifest → perceive (one job per clip, in parallel) → assemble | **AWS Step Functions** | `patchwork-process-pass` | **$0.000002** (free-tier sized) |

### Step 4 · Perception: video → measured defects (OpenCV 5)

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 4a | Per clip: frame triage, privacy blur, road-pitch estimate, **segmentation in OpenCV 5 `ENGINE_NEW`**, bird's-eye view, **area in m²** | **AWS Batch on Graviton Spot** (4 vCPU per clip, 10 clips in parallel) | `patchwork-perceive` | 9.5 vCPU-h ≈ **$0.12** (estimate) for 24 clip-runs. **Measured: $0.0019 per km** |
| 4b | Per pass: localisation on the road, tracking, evidence images | **AWS Batch** | `patchwork-assemble` | 1.1 vCPU-h ≈ **$0.01** (estimate) |
| 4c | Networking for the workers: public subnets, no NAT gateway, free S3 gateway endpoint | **Amazon VPC** | `patchwork` VPC 10.42.0.0/16 | Public IPv4 for Batch workers: **$0.04** |
| 4d | Job logs and pipeline metrics | **Amazon CloudWatch** (Logs, dashboard `patchwork-pipeline`) | `/patchwork/batch` | **$0.00** (within free tier) |

### Step 5 · The defect register (database)

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 5a | Store road segments, schools/hospitals/bus stops, observations, defects, status history, work packages, approvals | **Amazon Aurora Serverless v2** (PostgreSQL 17 + PostGIS), scales 0–4 ACU, **auto-pauses after 10 min** | cluster `patchwork-register` | **$0.0068** |
| 5b | Database access with no open port (pipeline jobs and laptop) | **RDS Data API** | (part of Aurora) | Included above |
| 5c | Database password, never in code | **AWS Secrets Manager** | RDS-managed secret | **$0.0002** |

### Step 6 · Show the results on a map

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 6a | Static viewer page plus the register exported as GeoJSON | **Amazon S3** | `patchwork-682839842398-site` | Included in S3 |
| 6b | Public HTTPS URL: https://d3mt6jrs1ynczo.cloudfront.net | **Amazon CloudFront** (private bucket via Origin Access Control) | distribution `E1877026KTY3HX` | **$0.00** (free tier) |
| 6c | Basemap tiles | **Amazon Location Service** | API key `patchwork-viewer-maps` (tiles only, viewer domain only) | **$0.00006** |

### Step 7 · The agent plans repairs, and a human decides

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 7a | Reasoning model of the "Ward Engineer's Assistant". Its tools query the register, group defects, estimate material and draft work orders | **Amazon Bedrock: Amazon Nova Pro / Lite** (first-party models only) | `apac.amazon.nova-pro-v1:0` | **$0.16** (about 148 k tokens in total; the 31-package planning run alone is about $0.12) |
| 7b | Work orders (Markdown) and agent traces | **Amazon S3** | `…-artifacts/workorders/`, `…/traces/` | Included in S3 |
| 7c | Approval gate: the workflow waits for a person; approve → MOCK ticket, reject → override recorded, no answer → expires after 7 days | **AWS Step Functions** (`waitForTaskToken`) | `patchwork-approve-work-package` | Included in Step 3c |

### Step 8 · Guardrails and cost tracking

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 8a | One role per component. A permissions boundary means no role can give itself more rights | **AWS IAM** | `patchwork-*` roles, `patchwork-boundary` | free |
| 8b | Alarm on real money (after credits) | **AWS Budgets** | `patchwork-real-spend` | free |
| 8c | Usage, credits and net per service for this report | **AWS Cost Explorer** (API, $0.01 per call) | used by `make cost-report` | **$0.24** (24 calls) |
| 8d | Infrastructure as code, state stored in S3 | **Terraform → S3** | `patchwork-682839842398-tfstate` | Included in S3 |

## 2. Per-service totals, as billed by AWS (2026-10-12 → 13)

| AWS service | Usage (gross) | Promotional credits | Main driver |
|---|---|---|---|
| Amazon EC2 – Compute | $3.03 | −$3.02 | **$3.01 is the development box** (t3a.xlarge, us-east-1, 20 h). Batch Spot so far: $0.008 billed (estimate ≈ $2.30 once billing catches up, see Step 1–4) |
| Amazon S3 | $0.83 | −$0.41 | $0.42 cross-region transfer (Mumbai → dev box in us-east-1), $0.41 requests (74 k write/list requests: training images, clips, pipeline outputs) |
| AWS Data Transfer (credit line) | – | −$0.50 | Credit applied to the S3 and EC2 transfer above |
| EC2 – Other | $0.27 | −$0.21 | EBS disk of the dev box ($0.21), transfer |
| AWS Cost Explorer | $0.24 | −$0.24 | Cost-report API calls |
| Amazon Bedrock (Nova) | $0.16 | −$0.16 | Agent runs, A/B test |
| Amazon VPC | $0.15 | −$0.15 | Public IPv4 addresses (dev box $0.11, Batch workers $0.04) |
| Amazon Aurora (RDS) | $0.007 | −$0.007 | Register, mostly paused |
| Amazon ECR | $0.0006 | −$0.0006 | Image storage |
| Secrets Manager, Location, EventBridge, Step Functions | < $0.001 | covered | |
| CloudFront, CloudWatch, KMS, Glue, ECS | $0.00 | – | Within the free tier |
| **Total** | **$4.69** | **−$4.69** | **Net $0.00** |

The per-service credit amounts do not always equal the per-service usage. AWS applies part of the credit on a separate "AWS Data Transfer" line. The **total** is exactly offset: net $0.0000000055.

## 3. What one kilometre costs (the proposal's metric)

| Measure | Value | Target |
|---|---|---|
| Perception compute per km: measured run time (133 s on 4 vCPU per km) × current Graviton Spot price ($0.0127/vCPU-h) | **$0.0019/km** | < $0.02 ✅ |
| Upper bound: all processing spend so far ÷ km processed (includes data rendering and training) | $0.034/km | – |
| A full 28.4 km pass | ≈ $0.05 of compute, 17–19 min wall-clock | – |

## 4. Services we chose **not** to use (and why)

| Service | Why not |
|---|---|
| NAT Gateway | It would cost about $33/month, more than all the compute. Public subnets plus an S3 gateway endpoint do the job |
| SageMaker (GPU) | The owner asked for CPU training. Batch Graviton Spot trains the model for about $2 per run |
| SQS, DynamoDB | Step Functions + Batch retries and the register's unique index already give buffering and idempotency |
| API Gateway, Lambda, Cognito | Not needed for the midpoint: the viewer reads a published GeoJSON. Planned for the second-half console and agent tools |
| AWS Marketplace / third-party Bedrock models / Route 53 domains / Savings Plans / paid Support | Not covered by promotional credits, so banned by D-27 |

## 5. How to check these numbers yourself

```bash
make cost-report          # rewrites 02-COST-REPORT.md: usage / credits / net per service, coverage table
make services-inventory   # lists every tagged AWS resource (03-SERVICES-USED.md)
```

In the AWS console: **Billing → Credits** (balance and expiry), and **Cost Explorer** (group by Service, filter Charge type = Usage / Credit).
