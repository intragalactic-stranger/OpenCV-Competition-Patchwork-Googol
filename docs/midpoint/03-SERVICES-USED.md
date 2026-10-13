# AWS services used

All services run in **ap-south-1 (Mumbai)**, except the global ones: CloudFront, IAM, Budgets and Cost Explorer.

- **Provisioning:** everything is created by Terraform (`infra/terraform/`) and tagged `Project=patchwork`.
- **Payment:** everything is paid by **AWS promotional credits**. Only first-party AWS services are used, and the cost report checks credit coverage per service ([02-COST-REPORT](02-COST-REPORT.md), decision D-27).

**Status:** ✅ deployed and used · ⏭ planned before the checkpoint · 🅿️ second half · ✖ dropped (with the reason)

## How the services fit together (as deployed)

```
 uploader (capture app stand-in) ─► [S3 raw]  clips + GNSS/IMU, manifest.json last (ground truth never uploaded)
                                       │ Object Created (manifest.json)
                                       ▼
                               [EventBridge rule] ─► [Step Functions: patchwork-process-pass]
                                                        │ 1. read manifest (S3 SDK integration)
                                                        │ 2. Batch .sync  "perceive"  array job, one child per clip
                                                        │ 3. Batch .sync  "assemble"  one job per pass
                                                        ▼
                     [AWS Batch · EC2 Graviton Spot · 0–32 vCPU]  ◄── arm64 images from [ECR]
                      perceive: triage · privacy blur · pitch · segmentation (OpenCV 5 DNN ENGINE_NEW) · m²
                      assemble: localisation · tracking · evidence images
                         │                         │                                  │
                         ▼                         ▼                                  ▼
               [S3 artifacts] runs/, models/   [Aurora Serverless v2 PostgreSQL + PostGIS]   [S3 site] ─► [CloudFront] map viewer
                                               via [RDS Data API] (no open ports)               basemap: [Amazon Location]
                                               credentials in [Secrets Manager]

 Training (CPU only): [AWS Batch Graviton Spot, 32 vCPU] ─► model.onnx ─► [S3 artifacts/models/]
 Data generation:     [AWS Batch array jobs] render the synthetic survey ─► [S3 datasets]
 Guardrails:          [IAM + permissions boundary] · [AWS Budgets: real-spend alarm] · [Cost Explorer] · [CloudWatch Logs]
```

## Service by service

| Service | What it does in Patchwork | Configuration highlights | Why this one | Covered by credits | Status |
|---|---|---|---|---|---|
| **Amazon S3** | 5 buckets: `raw` (uploads, 30-day expiry), `artifacts` (models, pipeline runs), `datasets` (open + synthetic data), `site` (viewer), `tfstate` | SSE-S3 encryption, all public access blocked, lifecycle rules, EventBridge notifications on `raw` | Cheapest durable storage; event source for the pipeline | ✅ verified | ✅ |
| **AWS Batch on EC2 Graviton Spot** | Runs every heavy job: rendering the synthetic survey (60 clips), dataset preparation, **CPU model training**, and the perception pipeline | Managed compute environment, `SPOT_PRICE_CAPACITY_OPTIMIZED`, c7g/c6g/m7g/c8g, **min 0 vCPU** (nothing runs when idle), retries on Spot interruption | Arm CPUs are cheap and fast for OpenCV; Spot is about 70% cheaper; scales to zero | ✅ verified (EC2) | ✅ |
| **Amazon ECR** | Two arm64 images: `patchwork-batch` (pipeline) and `patchwork-train` (CPU PyTorch training) | Scan on push, keep last 10 | Native for Batch | ⏭ verify in next report | ✅ |
| **AWS Step Functions** | Orchestrates one survey pass: manifest → parallel perceive → assemble | Standard workflow, Batch `.sync` integration, error logging | Visual run graph for the demo; later also the human-approval gate | ⏭ verify | ✅ |
| **Amazon EventBridge** | Starts the pipeline when a pass's `manifest.json` lands in S3 | Rule on `Object Created`, suffix `manifest.json` | No polling; the upload *is* the trigger | ⏭ verify | ✅ |
| **Amazon Aurora Serverless v2 (PostgreSQL 17 + PostGIS)** | The **defect register**: road segments, POIs, observations, defects, status history, agent tables | **0–4 ACU, auto-pause after 10 min idle**, private subnets, no inbound rules | Spatial queries need PostGIS; scales to zero when idle | ⏭ verify | ✅ |
| **RDS Data API** | The only way into the database (pipeline jobs and the dev box) | IAM + Secrets Manager authentication | No NAT, no bastion, no open port | (part of Aurora) | ✅ |
| **AWS Secrets Manager** | Holds the database master credentials (rotated by RDS) | Managed by RDS (`manage_master_user_password`) | No password in code or config | ⏭ verify | ✅ |
| **Amazon CloudFront** | Serves the map viewer over HTTPS | Origin Access Control to a private bucket; `data/*` never cached | Public demo URL without a public bucket | ⏭ verify | ✅ |
| **Amazon Location Service** | Basemap tiles for the viewer | API key restricted to tile reads from the viewer's domain only | Keeps the map on AWS (no third-party tile service) | ⏭ verify | ✅ |
| **Amazon VPC** | Public subnets for Batch workers, private subnets for Aurora, free S3 gateway endpoint | **No NAT gateway** (decision D-05) | A NAT gateway would cost more than all the compute | ✅ verified | ✅ |
| **Amazon CloudWatch Logs** | Logs for every Batch job and pipeline execution | 14-day retention | Debugging and evidence | ✅ verified | ✅ |
| **AWS IAM** | One role per component plus the `patchwork-boundary` permissions boundary, so no role can escalate | Least privilege; the dev-box role cannot change itself | Security baseline | free | ✅ |
| **AWS Budgets** | `patchwork-real-spend`: alarm on cost **after credits** at $0.01 | Email to the owner | Guarantees "no real money" is noticed immediately | free (2 budgets) | ✅ |
| **AWS Cost Explorer** | Source of the cost report: usage, credits, net per service | API from `make cost-report` | Single source of truth for spend | ✅ verified | ✅ |
| **Amazon Bedrock (Amazon Nova)** | Reasoning model for the agent preview | APAC inference profiles `apac.amazon.nova-pro/lite-v1:0` confirmed available | First-party models only (no Marketplace) | ✅ verified | ⏭ (AWS account verification pending) |
| **Amazon Bedrock AgentCore** | Agent runtime and tool gateway for the agent preview | Strands agent; tools are functions with ID grounding | Managed agent loop and traces | ⏭ verify on first use | ⏭ (stretch) |
| **AWS Lambda** | Agent tools (Phase 5) | | Small, event-driven | ⏭ | ⏭ |
| Amazon SageMaker AI | ~~GPU training~~ | | **✖ Dropped**: the owner asked for CPU training (D-25); Batch Graviton does it for about $1 per run | n/a | ✖ |
| Amazon SQS, Amazon DynamoDB | ~~Clip buffering, idempotency keys~~ | | **✖ Not needed**: Step Functions + Batch retries buffer the work, and the register's unique index makes reloads idempotent | n/a | ✖ |
| Amazon API Gateway | ~~Viewer API~~ | | **✖ Not needed for the midpoint**: the assemble job publishes the register as GeoJSON to the site bucket | n/a | 🅿️ console |
| Amazon Cognito | Console sign-in | | Second-half console | n/a | 🅿️ |

"✅ verified" means Cost Explorer shows the service's usage fully offset by promotional credits (net $0.00). "⏭ verify" marks services new this session: Cost Explorer lags about 24 h, so they show up in the next `make cost-report` and are only scaled up once they appear there as ✅ covered (D-27 trial rule).

## Deployed resource inventory

Generated by `make services-inventory` (Resource Groups Tagging API, tag `Project=patchwork`).

<!-- INVENTORY:BEGIN -->
| Service | Count | Resources |
|---|---|---|
| batch | 7 | `patchwork-graviton-spot`, `patchwork-assemble:1`, `patchwork-perceive:1`, `patchwork-prepare:1`, `patchwork-synth-render:1`, `patchwork-train-cpu:1`, `patchwork-spot` |
| budgets | 1 | `patchwork-real-spend` |
| cloudfront | 1 | `E1877026KTY3HX` |
| ec2 | 13 | `igw-03c704a56c4275341`, `rtb-0722a307fa261b065`, `rtb-0bfe81f228dc351d6`, `sg-002be3a31805ebe9e`, `sg-03f851a15bc81222e`, `subnet-05e1a9ada6ab6f117`, `subnet-0651534bd5a42c545`, `subnet-06f8575f8bfb9935a` … (+5) |
| ecr | 2 | `patchwork-batch`, `patchwork-train` |
| events | 1 | `patchwork-pass-uploaded` |
| geo | 1 | `patchwork-viewer-maps` |
| iam | 2 | `patchwork-batch-instance`, `patchwork-boundary` |
| logs | 2 | `patchwork/batch`, `patchwork/pipeline-sfn` |
| rds | 4 | `cluster:cluster-4c6wrfqws7mlorewyc4vdeko5a`, `cluster:patchwork-register`, `db:patchwork-register-1`, `subgrp:patchwork-db` |
| s3 | 5 | `patchwork-682839842398-artifacts`, `patchwork-682839842398-datasets`, `patchwork-682839842398-raw`, `patchwork-682839842398-site`, `patchwork-682839842398-tfstate` |
| secretsmanager | 1 | `secret:rds!cluster-b7d0426f-d516-48fa-a434-d652e46a8790-k4S1m0` |
| states | 2 | `stateMachine:patchwork-approve-work-package`, `stateMachine:patchwork-process-pass` |

_42 tagged resources · generated 2026-10-13 11:56 UTC._
<!-- INVENTORY:END -->
