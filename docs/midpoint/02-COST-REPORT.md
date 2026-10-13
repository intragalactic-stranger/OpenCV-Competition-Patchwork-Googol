# Cost report

> **Generated** by `make cost-report` (`scripts/cost_report.py`) from **AWS Cost Explorer**. Do not edit the generated section by hand.
> Scope: all resources tagged `Project=patchwork` in account `682839842398`, region ap-south-1, plus the shared dev box listed separately.

## Summary

<!-- COST-SUMMARY:BEGIN -->
| Item | Value |
|---|---|
| Period | 2026-10-12 → 2026-10-14 (end exclusive) |
| Project usage (gross, before credits) | **$2.18** |
| Account usage since project start (gross) | $2.18 |
| Paid by AWS promotional credits | $2.18 |
| **Real money paid (net after credits)** | **$0.00** (guarded by the `patchwork-real-spend` budget: alert at $0.01) |
| Dev box (shared EC2 t3a.xlarge, us-east-1) | included above only if it is tagged |
| Planned monthly usage (from credits) | $300.00 |
| Account usage this month to date | $10.20 (3.4% of plan); net paid $0.00 |
| Kilometres processed (from the register) | 0.0 |
| **Cost per km processed** (processing services only) | n/a (no km processed yet) |
| Target cost per km (proposal) | < $0.02 |
| Generated | 2026-10-13 05:37 UTC by `make cost-report` |

⚠️ The `Project` cost-allocation tag is not active yet (or has no data), so this shows the **whole account**, including the dev box and anything unrelated.
<!-- COST-SUMMARY:END -->

## Credit coverage per service (must be ✅ for every row)

<!-- COST-CREDIT-COVERAGE:BEGIN -->
| AWS service | Usage | Paid by credits | Real money (net) | Covered? |
|---|---|---|---|---|
| Amazon Elastic Compute Cloud - Compute | $1.9552 | $1.9552 | $0.0000 | ✅ |
| EC2 - Other | $0.1548 | $0.1548 | $0.0000 | ✅ |
| Amazon Virtual Private Cloud | $0.0734 | $0.0734 | $0.0000 | ✅ |
| Amazon Bedrock | $0.0001 | $0.0001 | $0.0000 | ✅ |

**All services fully covered by promotional credits.**
<!-- COST-CREDIT-COVERAGE:END -->

## Spend by AWS service

<!-- COST-BY-SERVICE:BEGIN -->
| AWS service | What it is used for | Usage to date (gross, paid by credits) |
|---|---|---|
| Amazon Elastic Compute Cloud - Compute | Batch Graviton Spot instances (and dev box if untagged) | $1.96 |
| EC2 - Other | EBS volumes, data transfer | $0.15 |
| Amazon Virtual Private Cloud | Networking (no NAT) | $0.07 |
| Amazon Bedrock | Claude for the agent | $0.00 |
| Amazon Simple Storage Service | Clips, crops, overlays, models, state | $0.00 |
<!-- COST-BY-SERVICE:END -->

![Cost by service](assets/cost_by_service.png)

## Spend by phase

<!-- COST-BY-PHASE:BEGIN -->
| Phase | Spend |
|---|---|
| (no tagged spend yet) | $0.00 |
<!-- COST-BY-PHASE:END -->

## Who pays: AWS promotional credits (no real money)

Everything runs on **AWS promotional credits** (decision [D-27](../plan/11-decisions-and-risks.md)). The table above separates gross usage, the part paid by credits, and the **real money paid, which must stay $0.00**. A dedicated AWS Budget (`patchwork-real-spend`) measures cost *after* credits and e-mails the owner at the first cent. Services that credits usually exclude are not used: Marketplace, third-party Bedrock models, domain registration, Savings Plans, paid Support.

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
