# 09: AWS infrastructure, access and cost

Region: **ap-south-1 (Mumbai)**. Monthly cap: **$300**. Everything is in Terraform and tagged `Project=patchwork`, `Phase=<n>`, `Owner=googol`.

## 1. Access setup (one-time, done by you)

### 1.1 Attach an IAM role to this EC2 instance
1. IAM → Roles → *Create role* → trusted entity **EC2** → name `patchwork-dev-box`.
2. Attach the managed policy **`PowerUserAccess`** (everything except IAM/Organizations).
3. Add the inline policy `infra/iam/patchwork-iam-scoped.json` (replace `ACCOUNT_ID`). It lets Terraform manage **only** `patchwork-*` roles and policies, and pass only `patchwork-*` roles.
4. EC2 → this instance → *Actions → Security → Modify IAM role* → choose `patchwork-dev-box`.
5. Tell me, and I'll verify with `aws sts get-caller-identity`.

**Privilege-escalation guard (applied 2026-10-12, decision D-18).** IAM write access is dangerous, because a role that can edit roles can grant itself admin. So:
- Every `patchwork-*` role **must** be created with the permissions boundary `patchwork-boundary` (`infra/iam/patchwork-boundary.json`: everything except `iam:*`, `organizations:*`, `account:*`). Creating a role without it is denied.
- The boundary can't be removed from a role, and the boundary policy itself can't be edited or deleted.
- The `patchwork-dev-box` role and its instance profile are **read-only to themselves**. Only a human admin in the console can change the dev box's permissions.
- Verified by test: no-boundary create → denied; remove boundary → denied; attach AdministratorAccess to the dev box → denied; edit boundary → denied.
- Terraform sets `permissions_boundary = "arn:aws:iam::<acct>:policy/patchwork-boundary"` on every role.

### 1.2 Enable Bedrock model access
We use **Amazon Nova** models (owner's choice, D-17). Amazon's first-party models generally need no use-case form; if a call returns `AccessDeniedException`, enable them under Bedrock console (ap-south-1) → *Model access*.

### 1.3 Cost Explorer and the cost-allocation tag
- Billing → Cost Explorer → enable (free; data appears within 24 h).
- Billing → Cost allocation tags → activate **`Project`** after the first tagged resource exists. It can take up to 24 h to show.
- Both need the management (payer) account. If this is a member account in an Organization, ask the payer admin.

## 2. Terraform layout (`infra/terraform/`)

```
bootstrap/            S3 state bucket (versioned, S3-native locking) + AWS Budget (run once, local state)
modules/
  storage/            S3 raw (30-day expiry), artifacts, datasets (Intelligent-Tiering), KMS key, S3 gateway endpoint
  network/            VPC (2 AZs), public subnets for Batch, private subnets for Aurora, no NAT
  db/                 Aurora PostgreSQL Serverless v2 (min 0 ACU / auto-pause, max 4 ACU), Data API, Secrets Manager
  ingest/             EventBridge rule, SQS + DLQ, EventBridge Pipe → Step Functions
  batch/              ECR repo, compute env (Graviton c7g/m7g Spot, 0–16 vCPU), job queue, job definition
  pipeline/           Step Functions process-clip state machine, Lambdas (register-load, match-passes), DynamoDB jobs table
  training/           SageMaker execution role, S3 prefixes (jobs launched from Python, not Terraform)
  agent/              AgentCore runtime + gateway, tool Lambdas, approval state machine, approvals table (Phase 5)
  viewer/             S3 site bucket + CloudFront (OAC), API Gateway HTTP API + Lambdas, Amazon Location map/API key
  observability/      CloudWatch dashboard, alarms (DLQ depth, Batch failures, budget), log retention 14 days
envs/dev/             composition, default_tags, variables
```

## 3. Services: what, why, config

| Service | Why | Key config | Midpoint? |
|---|---|---|---|
| S3 | Clips, artefacts, datasets, site | KMS, block public, lifecycle (raw 30 d) | ✅ |
| EventBridge + SQS (+DLQ) | Decoupled, retryable ingest | DLQ after 3 receives | ✅ |
| Step Functions | Pipeline orchestration + approval via task token | Standard workflows | ✅ |
| AWS Batch on EC2 Graviton **Spot** | CPU-bound OpenCV work at about 70% discount | `SPOT_PRICE_CAPACITY_OPTIMIZED`, c7g/m7g, min 0 vCPU | ✅ |
| ECR | arm64 pipeline image | Scan on push, keep last 10 | ✅ |
| DynamoDB | Job state, idempotency, approval tokens | On-demand, TTL | ✅ |
| Aurora Serverless v2 PostGIS | Spatial register | min 0 ACU (auto-pause) / max 4, Data API | ✅ |
| SageMaker AI | GPU training, then off | `ml.g5.xlarge`, managed Spot, max runtime 3 h, checkpoints to S3 | ✅ |
| Lambda | Register loader, tools, API | arm64, Python 3.12, no VPC | ✅ |
| CloudFront + S3 website | Viewer | OAC, cache static | ✅ |
| API Gateway (HTTP API) | Viewer/console API | IAM/Cognito auth in Phase 7 | ✅ (read-only) |
| Amazon Location Service | Map tiles, SnapToRoads, reverse geocode | API key restricted to the CloudFront domain | ✅ |
| Bedrock (Amazon Nova) | Agent reasoning | APAC inference profile if needed | 5a |
| Bedrock AgentCore | Agent runtime, gateway, memory, traces | | 5a |
| CloudWatch + X-Ray (OTel) | Metrics, logs, traces, dashboard | 14-day log retention | ✅ |
| KMS, IAM, Secrets Manager | Security | One CMK, least-privilege roles | ✅ |
| AWS Budgets + Cost Explorer | Cost guard and cost report | $300; alerts at 50/80/100% (actual) and 100% (forecast) | ✅ |

## 3a. Paying with promotional credits only (decision D-27)

The account runs on **AWS promotional credits**, and the owner must never pay real money.

| Rule | How it is enforced |
|---|---|
| Real spend stays at $0.00 | Budget `patchwork-real-spend`: monthly, **cost after credits**, alert e-mail at > $0.01 actual or > $1 forecast (Terraform `bootstrap/`) |
| Only first-party AWS services | No AWS Marketplace subscriptions, no third-party Bedrock models (Amazon Nova only, D-17), no Route 53 domain purchase, no Savings Plans / RIs, no paid Support plan. These are the usual promotional-credit exclusions. |
| Credits really are applied | `make cost-report` shows gross usage, the amount covered by credits, and net paid, from Cost Explorer `RECORD_TYPE`. Verified: Sep 2026 $32.72 usage, $32.72 credits; Oct to date fully offset |
| Credit balance and expiry | Not exposed by any API: the owner checks **Billing → Credits** (remaining amount, expiry date, eligible services) once a month |
| Burn rate stays small | Spot everywhere, no NAT, no GPU (D-25), Aurora auto-pause, S3 lifecycle; planned usage ≤ $300/month of credits |

## 4. Cost model

### 4.1 Midpoint (about 4 weeks) estimate, in USD
| Line | Estimate | Assumption |
|---|---|---|
| SageMaker training (ml.g5.xlarge Spot) | 15–35 | 15–25 GPU-hours across experiments |
| Aurora Serverless v2 | 15–40 | Auto-pause when idle; ~0.5–2 ACU while working |
| Batch Graviton Spot | 3–10 | ~10 full-corridor passes × ~0.3 instance-hours |
| S3 (≤ 150 GB incl. datasets) + transfer | 3–8 | |
| Bedrock (agent, 5a) | 5–25 | A few hundred agent runs during development |
| AgentCore, Lambda, SFN, EventBridge, SQS, DynamoDB, API GW, CloudFront, Location | 3–12 | Mostly free tier or near-zero |
| CloudWatch, KMS, Secrets Manager | 3–8 | |
| **Project total (excluding the dev box)** | **≈ $50–140** | |
| Dev EC2 box (t3a.xlarge, us-east-1, shared) | ≈ $0.15/h → ≈ $110/month if on 24/7 | Reported separately; stop it when not working to save money |

### 4.2 Steady-state cost per km (the proposal's headline number)
At 2,000 km/month: Batch ≈ $18, S3 ≈ $25, Aurora ≈ $45, Bedrock ≈ $30, other ≈ $25 → **≈ $143/month ≈ $0.007/km** (proposal §5.1). We measure the real value from Cost Explorer ÷ km processed.

### 4.3 Guardrails
- Budget alarms (50/80/100% actual, 100% forecast) → email.
- No NAT gateway. No always-on GPU. Aurora auto-pause. Batch min vCPU 0.
- `make teardown-expensive` (Aurora snapshot + delete, Batch CE to 0) and `make teardown` (everything except the state bucket and datasets).
- SageMaker `MaxRuntimeInSeconds` on every job; Spot with checkpointing.

## 5. Cost reporting for the grant (`scripts/cost_report.py`, `make cost-report`)
1. `ce:GetCostAndUsage`, DAILY + MONTHLY, `UnblendedCost`, grouped by `SERVICE`, filter `Tag Project=patchwork`. Also unfiltered account total and EC2 (dev box) cost by instance ID via resource-level data, if enabled.
2. Writes `docs/midpoint/02-COST-REPORT.md` (between markers) + `docs/midpoint/assets/cost_by_service.png` + CSV.
3. Adds **km processed** (from the register) → cost per km, and spend by phase (tag `Phase`).
4. Before the tag is active (first 24 h), it falls back to the service-level account view and says so.
