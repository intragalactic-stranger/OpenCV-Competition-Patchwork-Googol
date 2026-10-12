# AWS services used

Region **ap-south-1 (Mumbai)**. All resources are created by Terraform (`infra/terraform/`) and tagged `Project=patchwork`.
**Status:** ✅ in use · 🔄 being set up · ⏭ planned before the checkpoint · 🅿️ second half

## How the services fit together

```
 Synthetic dashcam pass ─► [S3 raw] ─► [EventBridge] ─► [SQS + DLQ] ─► [Step Functions]
                                                                          │
                     ┌────────────────────────────────────────────────────┤
                     ▼                                                    ▼
         [AWS Batch · EC2 Graviton Spot]                         [Lambda: register-load]
          OpenCV 5 container from [ECR]                                   │
          triage · blur · undistort · bird's-eye ·                        ▼
          segment (DNN ENGINE_NEW) · measure m²              [Aurora Serverless v2 + PostGIS]
                     │                                                    │
                     ▼                                                    ▼
         [S3 artifacts] crops/overlays                 [API Gateway + Lambda] ─► [CloudFront + S3] map viewer
         [DynamoDB] job state/idempotency                                         [Amazon Location] tiles, snap-to-road
 [SageMaker AI] training (GPU Spot) ─► model.onnx ─► S3
 [Bedrock AgentCore + Amazon Nova on Bedrock] agent ─► [Lambda tools] ─► [Step Functions] approval (task token)
 [CloudWatch · X-Ray] metrics/logs/traces    [AWS Budgets · Cost Explorer] cost guard + report    [KMS · IAM · Secrets Manager]
```

## Service by service

| Service | Role in Patchwork | Configuration highlights | Why this, not something else | Status |
|---|---|---|---|---|
| **Amazon S3** | Stores blurred clips (30-day expiry), crops, overlays, models, traces, work-order PDFs, the viewer site, Terraform state | KMS encryption, public access blocked, lifecycle rules, Intelligent-Tiering for datasets | Cheapest durable storage; event source for the pipeline | ⏭ |
| **Amazon DynamoDB** | Job state + idempotency keys (a Spot retry never duplicates); Terraform lock; approval tokens | On-demand, TTL | Single-digit-ms conditional writes, near-zero idle cost | ⏭ |
| **AWS Budgets** | $300/month cap with alerts at 50/80/100% and a forecast alert | Email notifications | Cost guardrail from day 1 | ⏭ |
| **AWS Cost Explorer** | Source of the cost report and cost per km | Filter by tag `Project=patchwork` | Single source of truth for spend | ⏭ |
| **Amazon EventBridge** | Fires when a clip's metadata lands in S3 | Rule on the `.meta.json` suffix; Pipe → Step Functions | Decoupled, no polling | ⏭ |
| **Amazon SQS (+ DLQ)** | Buffers clips; failed clips go to a dead-letter queue | maxReceiveCount 3, DLQ alarm | Back-pressure and retry without code | ⏭ |
| **AWS Step Functions** | Orchestrates the per-clip pipeline; later also holds the **human approval gate** (task token) | Standard workflows, Batch `.sync` integration | One mechanism for orchestration and approval, with a visual run graph for the demo | ⏭ |
| **AWS Batch on EC2 Graviton Spot** | Runs the OpenCV 5 perception container | c7g/m7g Spot, `SPOT_PRICE_CAPACITY_OPTIMIZED`, min 0 vCPU | CPU-bound vision work; Arm matches phones; Spot keeps cost per km tiny | ⏭ |
| **Amazon ECR** | Holds the arm64 pipeline image | Scan on push, keep last 10 | Native for Batch | ⏭ |
| **Amazon SageMaker AI** | Trains the segmentation model on GPU, then shuts down | `ml.g5.xlarge` managed Spot, checkpoints, max runtime 3 h | Pay only for training minutes; no idle GPU | ⏭ |
| **Amazon Aurora Serverless v2 (PostgreSQL + PostGIS)** | The defect register: spatial dedup, road joins, cross-pass matching | min 0 ACU (auto-pause), max 4 ACU, Data API | A geospatial problem needs PostGIS; serverless keeps idle cost near zero | ⏭ |
| **AWS Lambda** | Register loader, viewer API, agent tools (with ID grounding) | arm64, Python 3.12, outside the VPC (Data API) | Event-driven, no servers, no NAT needed | ⏭ |
| **Amazon API Gateway (HTTP API)** | Viewer/console API | Throttling; auth added in the second half | Cheapest managed HTTP front door | ⏭ |
| **Amazon CloudFront** | Serves the map viewer | Origin Access Control to S3 | HTTPS + global caching for the demo | ⏭ |
| **Amazon Location Service** | Map tiles, snap-to-road, reverse geocoding | API key restricted to the viewer domain | Keeps the geo stack on AWS | ⏭ |
| **Amazon Bedrock (Amazon Nova)** | Reasoning model for the agent (Nova Pro/Lite); multimodal fallback for defect attributes | APAC inference profile if required | Managed, no GPU hosting | ⏭ (stretch) |
| **Amazon Bedrock AgentCore** | Agent runtime, tool gateway, memory, per-run traces | Strands agent; tools are Lambdas via the Gateway | Managed agent loop and traces to show judges | ⏭ (stretch) |
| **Amazon CloudWatch + AWS X-Ray** | Metrics (km, frames, stage timings, cost/km), logs, traces, alarms, dashboard | EMF metrics, 14-day log retention, OTel | Observability in one place | ⏭ |
| **AWS KMS · IAM · Secrets Manager** | Encryption, least privilege, DB credentials | One CMK; one role per component | Security baseline | ⏭ |
| **Amazon VPC** | Private subnets for Aurora; public subnets for Batch; S3 gateway endpoint | **No NAT gateway** | Saves about $33+/month | ⏭ |
| **Amazon Cognito** | Console sign-in (engineer vs public) | | Second-half console | 🅿️ |

> Status values move from ⏭ to ✅ as each service is deployed. The deployed resource list can be regenerated with `make services-inventory` (Resource Groups Tagging API, filter `Project=patchwork`).

## Deployed resource inventory

<!-- INVENTORY:BEGIN -->
[[TBD: generated by `make services-inventory`]]
<!-- INVENTORY:END -->
