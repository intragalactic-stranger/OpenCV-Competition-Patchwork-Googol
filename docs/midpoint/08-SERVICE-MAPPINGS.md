# Service mappings: which AWS service does what, and what it cost

> **One page for the reviewer.** It follows the system step by step, from raw data to a filed work order. For each step it gives the AWS service, its purpose, its resource name and the credits it consumed.
> **Billing rule:** everything is paid by **AWS promotional credits**, and real money paid is **$0.00** (decision D-27).
> **Figures** come from AWS Cost Explorer (`UnblendedCost`, record types *Usage* and *Credit*), as of **2026-10-13 20:30 UTC**. Refresh with `make cost-report`, which rewrites [02-COST-REPORT](02-COST-REPORT.md).

## 0. The money in one table

| Period | Usage (gross) | Paid by promotional credits | **Real money paid** |
|---|---|---|---|
| Project build (2026-10-12 → 13, whole account since the project started) | $9.23 | −$9.23 | **$0.00** |
| October 2026 month to date (whole account) | $17.24 | −$17.24 | **$0.00** |
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
| 2b | Train SegFormer-B0 on CPU (`seg-v2`): 12 epochs in 3.9 h. Export ONNX, check OpenCV 5 parity, evaluate | **AWS Batch on Graviton Spot** (32 vCPU, c7g.8xlarge) | `patchwork-train-cpu` | **$1.70 billed** (c7g.8xlarge Spot; includes a stopped first attempt) |
| 2b′ | Fine-tune `seg-v2` → **`seg-v3`** with 1,788 look-alike frames as "not damage": 4 epochs, 2.7 h of training. AWS reclaimed the Spot instance 3 times; each time Batch restarted the job and it resumed from the last S3 checkpoint | **AWS Batch on Graviton Spot** (32 vCPU, c6g.8xlarge) | `patchwork-train-cpu` | 3.2 instance-h × $0.31–0.41 ≈ **$1.20** (estimate, not yet billed) |
| 2c | Keep the models, checkpoints and metrics | **Amazon S3** | `…-artifacts/models/seg-v2/`, `…/seg-v3/` | Included in S3 |

### Step 3 · A survey pass is uploaded: the pipeline starts by itself

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 3a | The uploader puts clips + GNSS/IMU into the raw bucket and writes `manifest.json` last. Ground truth is never uploaded | **Amazon S3** | `patchwork-682839842398-raw` (30-day expiry) | Included in S3 |
| 3b | `manifest.json` arriving fires an event | **Amazon EventBridge** | rule `patchwork-pass-uploaded` | **$0.000002** |
| 3c | The workflow runs: read manifest → perceive (one job per clip, in parallel) → assemble | **AWS Step Functions** | `patchwork-process-pass` | **$0.000002** (free-tier sized) |

### Step 4 · Perception: video → measured defects (OpenCV 5)

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 4a | Per clip: frame triage, privacy blur, road-pitch estimate, **segmentation in OpenCV 5 `ENGINE_NEW`**, bird's-eye view, **area in m²** | **AWS Batch on Graviton Spot** (4 vCPU per clip, 10 clips in parallel) | `patchwork-perceive` | ≈ 19 vCPU-h ≈ **$0.25** (estimate) for 44 clip-runs (the held-out survey on `seg-v2` and again on `seg-v3`, plus tests). **Measured: $0.0021 per km** |
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
| 7a | Reasoning model of the "Ward Engineer's Assistant". Its tools query the register, group defects, estimate material and draft work orders | **Amazon Bedrock: Amazon Nova Pro / Lite** (first-party models only) | `apac.amazon.nova-pro-v1:0` | **$0.33** billed (all agent runs and A/B tests on both surveys; one road-wide planning run is 84–106 k tokens ≈ $0.10–0.12) |
| 7b | Work orders (Markdown) and agent traces | **Amazon S3** | `…-artifacts/workorders/`, `…/traces/` | Included in S3 |
| 7c | Approval gate: the workflow waits for a person; approve → MOCK ticket, reject → override recorded, no answer → expires after 7 days | **AWS Step Functions** (`waitForTaskToken`) | `patchwork-approve-work-package` | Included in Step 3c |

### Step 8 · Guardrails and cost tracking

| # | What happens | AWS service | Resource | Credits consumed |
|---|---|---|---|---|
| 8a | One role per component. A permissions boundary means no role can give itself more rights | **AWS IAM** | `patchwork-*` roles, `patchwork-boundary` | free |
| 8b | Alarm on real money (after credits) | **AWS Budgets** | `patchwork-real-spend` | free |
| 8c | Usage, credits and net per service for this report | **AWS Cost Explorer** (API, $0.01 per call) | used by `make cost-report` | **$0.24** (24 calls) |
| 8d | Infrastructure as code, state stored in S3 | **Terraform → S3** | `patchwork-682839842398-tfstate` | Included in S3 |

## 2. Per-service totals, as billed by AWS (2026-10-12 → 13, as of 20:30 UTC)

| AWS service | Usage (gross) | Promotional credits | Main driver |
|---|---|---|---|
| Amazon EC2 – Compute | $6.43 | −$6.41 | **$4.21 is the development box** (t3a.xlarge, us-east-1, about 28 h). **Batch Spot billed so far: $2.20**: `seg-v2` training on c7g.8xlarge $1.70, rendering and pipeline runs $0.49. The `seg-v3` fine-tune (≈ $1.20) and the `seg-v3` survey run (≈ $0.12) are not billed yet |
| Amazon S3 | $0.86 | −$0.43 | $0.43 cross-region transfer (Mumbai → dev box in us-east-1), $0.43 requests (training images, clips, pipeline outputs) |
| AWS Data Transfer (credit line) | – | −$0.51 | Credit applied to the S3 and EC2 cross-region transfer above |
| Amazon Aurora (RDS) | $0.57 | −$0.57 | Register: 3.1 ACU-hours of Serverless v2 while loading passes and running the agent ($0.55), storage I/O ($0.02). Pauses when idle |
| AWS Cost Explorer | $0.42 | −$0.42 | Cost-report API calls ($0.01 each) |
| EC2 – Other | $0.40 | −$0.33 | EBS disk of the dev box ($0.28), Batch worker disks ($0.05), transfer ($0.07) |
| Amazon Bedrock (Nova Pro) | $0.33 | −$0.33 | Agent runs and the A/B test: input tokens $0.26, output tokens $0.06 |
| Amazon VPC | $0.22 | −$0.22 | Public IPv4 addresses (dev box $0.15, Batch workers $0.07) |
| Secrets Manager, ECR, Location, EventBridge, Step Functions | $0.01 | covered | |
| CloudFront, CloudWatch, KMS, Glue, ECS | $0.00 | – | Within the free tier |
| **Total** | **$9.23** | **−$9.23** | **Net $0.00** |

**Expected once Spot billing catches up:** about **$10.6** (the $9.23 above + ≈ $1.2 for the `seg-v3` fine-tune + ≈ $0.2 for the `seg-v3` survey run), all paid by credits.

The per-service credit amounts do not always equal the per-service usage. AWS applies part of the credit on a separate "AWS Data Transfer" line. The **total** is exactly offset: net $0.0000000055.

## 3. What one kilometre costs (the proposal's metric)

| Measure | Value | Target |
|---|---|---|
| Perception compute per km: measured run time (147 s on 4 vCPU per km, `seg-v3`) × current Graviton Spot price ($0.0128/vCPU-h) | **$0.0021/km** | < $0.02 ✅ |
| Upper bound: all processing spend so far ÷ km processed (includes data rendering and training) | $0.064/km | – |
| A full 28.4 km pass | ≈ $0.06 of compute, 15–17 min wall-clock | – |

## 4. Services we chose **not** to use (and why)

| Service | Why not |
|---|---|
| NAT Gateway | It would cost about $33/month, more than all the compute. Public subnets plus an S3 gateway endpoint do the job |
| SageMaker | First half: the owner asked for CPU training, and Batch Graviton Spot trains the model for about $2 per run. Second half: GPU training runs on EC2 G instances through the same Batch setup (same container, Spot pricing, checkpoint resume), so no second training stack is needed |
| SQS, DynamoDB | Step Functions + Batch retries and the register's unique index already give buffering and idempotency |
| API Gateway, Lambda, Cognito | Not needed for the midpoint: the viewer reads a published GeoJSON. Planned for the second-half console and agent tools |
| AWS Marketplace / third-party Bedrock models / Route 53 domains / Savings Plans / paid Support | Not covered by promotional credits, so banned by D-27 |

## 5. Second half: services we will use, how they are configured, and projected credits

The second half (about 6 weeks) adds:
- the full agent on AgentCore,
- repair verification over 8 passes,
- the web console,
- the 40-scenario evaluation,
- a **stronger segmentation model trained on GPU**.

The first half was deliberately run on the cheapest settings: CPU training, everything auto-pausing, small models. Those settings proved the pipeline works. The second half is where accuracy is bought.

**How the projection was built.** Prices are **AWS list prices for ap-south-1** (AWS Pricing API, 2026-10-13) or **rates measured in our own bill**: Nova Pro at $0.94 per million input tokens and $3.76 per million output tokens. Quantities come from **measured first-half runs** (tokens per agent run, seconds per km, vCPU-hours per clip), scaled to the planned work. Every line has a cap enforced in AWS (§5.3).

### 5.1 GPU training configuration (the largest new compute item)

| Item | Plan |
|---|---|
| Instance | **EC2 `g6.xlarge`** (1× NVIDIA L4 24 GB, 4 vCPU, 16 GiB). Fallback **`g5.xlarge`** (1× A10G 24 GB) |
| Price (ap-south-1) | On-demand list **$0.97/h** (g6) and $1.21/h (g5). Spot today **$0.53–0.77/h** (g6) and $0.55–0.70/h (g5) |
| Run by | **AWS Batch**: a second compute environment `patchwork-gpu-spot` (ECS GPU AMI), Spot first, on-demand only if Spot is unavailable for > 2 h. Same container, plus CUDA PyTorch |
| Limits | max **2 instances** (8 vCPU), job timeout **12 h**, checkpoint every epoch to S3 (existing Spot-resume code), mixed precision |
| Model | SegFormer-**B2** (25 M parameters; B0 has 3.7 M) at the full 1920×448 road strip. Adds a severity/depth head and soft boundaries for depressions |
| Data | Real Pothole Mix + **5 synthetic training worlds** (4 new) with hard negatives: about 25 k images |
| Prerequisite | EC2 **G-instance quota** (currently 0). New quota requests are blocked while the old SageMaker GPU requests stay open, so the owner must close those support cases first |

| Training work | Runs | GPU-hours per run | GPU-hours |
|---|---|---|---|
| Architecture × resolution sweep (B0/B1/B2 × 2 sizes, 10 epochs each) | 6 | 6 | 36 |
| Final model, 3 random seeds (30 epochs; mean ± spread reported) | 3 | 17.5 | 52 |
| Depression/severity head, soft-boundary labels | 2 | 10 | 20 |
| **Total** | | | **≈ 110 GPU-h** |

At $0.60/h Spot that is $66. Allowing 20% for on-demand fallback and re-runs: **≈ $80**.

The hours are a planning estimate. As decision D-27 requires, a 1-epoch trial run measures the real throughput first, and this table is updated from that measurement.

### 5.2 Projected credits by service (second half)

| # | Service | What it is for in the second half | Basis of the estimate | Expected credits |
|---|---|---|---|---|
| 1 | **EC2 GPU via AWS Batch** | Segmentation training (§5.1) | 110 GPU-h × $0.60 Spot + 20% fallback | **$80** |
| 2 | **Amazon Bedrock: Amazon Nova Pro** | 40-scenario agent suite run live about 50 times (recorded responses in between) | Measured: about 12 k tokens per single-defect plan, about 106 k per road-wide plan → ≈ 1.36 M tokens ≈ **$1.47 per suite run** | **$74** |
| | | LLM-judge rubric scoring of work orders | About 15% of the suite cost | **$10** |
| | | Image context attributes (water, location, surface) for each defect's evidence image | About 10,000 images × 3 iterations × 1.6 k tokens | **$16** |
| 3 | **Amazon Aurora Serverless v2** | Register for 8-pass verification, the live console and the agent | $0.18 per ACU-hour (Mumbai list). Development 6 h/day × 42 d × 0.5 ACU, plus 2 weeks always-on demo period × 0.5 ACU, plus storage/I/O | **$40** |
| 4 | **EC2 development workstation** (t3a.xlarge, us-east-1) | Where the code is written and builds run | $0.1504/h list × about 12 h/day × 42 d, plus EBS and IPv4 | **$92** |
| 5 | **Amazon CloudWatch** | Dashboards (override rate, cost/km, time to approval), about 20 custom metrics, logs, traces | Metrics $0.30/month each, log ingestion, X-Ray | **$15** |
| 6 | **Amazon S3** (+ transfer) | 5 training worlds, 8-pass evaluation data, models, evidence images | ~150 GB-month, requests (first half: $0.41 per 74 k), transfer to the dev box | **$12** |
| 7 | **AWS Batch on Graviton Spot (CPU)** | Pipeline runs for evaluation: 2 worlds × 8 passes × (system + 4 ablations) × about 3 iterations ≈ 120 passes. RDD2022 external check | Measured **$0.054 per pass** | **$10** |
| 8 | **Bedrock AgentCore** (Runtime, Gateway, Memory) | Hosts the agent and its tools | $0.0895/vCPU-h + $0.00945/GB-h on active time. About 3,000 sessions at about $0.003 each, plus Gateway $0.005 per 1 k calls | **$9** |
| 9 | **AWS Batch on Graviton Spot (CPU)** | Rendering 4 new training worlds and 5 more held-out passes (about 170 clips) | Measured about 0.25 vCPU-h per clip | **$5** |
| 10 | **AWS Cost Explorer** API | Daily cost report | $0.01 per call | **$4** |
| 11 | ECR, Secrets Manager, Location, Step Functions, EventBridge, CloudFront | Images, secret, basemap tiles for reviewers, workflows, triggers, HTTPS | List prices; mostly within the free tier | **$4** |
| 12 | **Lambda, API Gateway, Cognito** | Console backend, agent tools behind the Gateway, sign-in | Mostly within the free tier | **$2** |
| | **Total second half (expected)** | | | **≈ $370** |
| | Lower case (Spot always available, 30 live suite runs, dev box stopped at night) | | | ≈ $260 |
| | Upper case (on-demand GPU, 80 live suite runs) | | | ≈ $470 |

**Combined view for the grant:** the first half used about **$10.6** of credits by the checkpoint ($9.23 billed as of 2026-10-13 20:30 UTC + about $1.4 of Spot still being billed). Most of it was the development box; the cloud pipeline itself is cheap by design. The second half is projected at **≈ $370 (range $260–470)**. The extra spend goes on GPU training, live agent evaluation and an always-on demo database, the three items deliberately kept at zero or near zero in the first half.

### 5.3 Boundaries: what stops spend from running away

| Guardrail | Setting |
|---|---|
| Real-money alarm | `patchwork-real-spend` budget, cost **after credits**, alert at the first cent (unchanged) |
| Credit-usage budget | New budget on **gross** usage: $300/month with alerts at 50/80/100% |
| Compute caps | Batch `maxvCpus`: CPU 32, GPU 8 (2 instances); job timeouts (train 12 h, perceive 1 h) |
| Database cap | Aurora 0–4 ACU, auto-pause after 10 min idle |
| LLM cap | Agent-suite runner refuses to start when the month's Bedrock usage passes its budget line; temperature 0; recorded-response mode for routine CI |
| Permissions | All roles stay under the `patchwork-boundary` permissions boundary. No role can raise its own limits |
| Trial first (D-27) | Every new service (GPU instances, AgentCore, API Gateway, Cognito) runs a small trial. It is scaled up only after the cost report shows it ✅ covered by credits |

## 6. How to check these numbers yourself

```bash
make cost-report          # rewrites 02-COST-REPORT.md: usage / credits / net per service, coverage table
make services-inventory   # lists every tagged AWS resource (03-SERVICES-USED.md)
```

In the AWS console: **Billing → Credits** (balance and expiry), and **Cost Explorer** (group by Service, filter Charge type = Usage / Credit).
