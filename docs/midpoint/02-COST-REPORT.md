# Cost report

> **Generated** by `make cost-report` (`scripts/cost_report.py`) from **AWS Cost Explorer**. Do not edit the generated section by hand.
> Scope: all resources tagged `Project=patchwork` in account `682839842398`, region ap-south-1, plus the shared dev box listed separately.

## Summary

<!-- COST-SUMMARY:BEGIN -->
| Item | Value |
|---|---|
| Period | 2026-10-12 → 2026-10-14 (end exclusive) |
| Total project spend | **$0.00** |
| Dev box (shared EC2 t3a.xlarge, us-east-1) | included above only if it is tagged |
| Monthly budget | $300.00 |
| Account spend this month to date | $0.00 (0.0% of budget) |
| Kilometres processed (from the register) | 0.0 |
| **Cost per km processed** (processing services only) | n/a (no km processed yet) |
| Target cost per km (proposal) | < $0.02 |
| Generated | 2026-10-13 03:45 UTC by `make cost-report` |

⚠️ The `Project` cost-allocation tag is not active yet (or has no data), so this shows the **whole account**, including the dev box and anything unrelated.
<!-- COST-SUMMARY:END -->

## Spend by AWS service

<!-- COST-BY-SERVICE:BEGIN -->
| AWS service | What it is used for | Spend to date |
|---|---|---|
| Amazon Elastic Compute Cloud - Compute | Batch Graviton Spot instances (and dev box if untagged) | $0.00 |
| EC2 - Other | EBS volumes, data transfer | $0.00 |
<!-- COST-BY-SERVICE:END -->

![Cost by service](assets/cost_by_service.png)

## Spend by phase

<!-- COST-BY-PHASE:BEGIN -->
| Phase | Spend |
|---|---|
| (no tagged spend yet) | $0.00 |
<!-- COST-BY-PHASE:END -->

## Where the money goes and why (narrative, maintained by hand)

- **Training (SageMaker GPU, Spot)** is the largest one-off cost. Each experiment runs on `ml.g5.xlarge` Spot with a hard max runtime and checkpoints, and no GPU is left running.
- **Processing (Batch on Graviton Spot)** is the per-km cost. It is small because frame triage keeps only about 10% of frames and Spot is roughly 70% cheaper.
- **Database (Aurora Serverless v2)** auto-pauses when idle.
- **No NAT gateway** (it would cost more than all compute combined). See [decision D-05](../plan/11-decisions-and-risks.md).

## Pre-build estimate (for comparison)

| Line | Estimate for the first half |
|---|---|
| SageMaker training | $15–35 |
| Aurora Serverless v2 | $15–40 |
| Batch Graviton Spot | $3–10 |
| S3 + transfer | $3–8 |
| Bedrock + AgentCore (stretch) | $5–25 |
| Lambda, Step Functions, EventBridge, SQS, DynamoDB, API GW, CloudFront, Location | $3–12 |
| CloudWatch, KMS, Secrets Manager | $3–8 |
| **Total (excluding dev box)** | **≈ $50–140** |

## How to regenerate

```bash
make cost-report          # rewrites the generated sections above + assets/cost_by_service.png + assets/cost.csv
```
