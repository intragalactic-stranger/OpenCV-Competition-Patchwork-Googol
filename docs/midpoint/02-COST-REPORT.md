# Cost report

> **Generated** by `make cost-report` (`scripts/cost_report.py`) from **AWS Cost Explorer**. Do not edit the generated section by hand.
> Scope: all resources tagged `Project=patchwork` in account `[[TBD: account id]]`, region ap-south-1, plus the shared dev box listed separately.

## Summary

<!-- COST-SUMMARY:BEGIN -->
| Item | Value |
|---|---|
| Period | [[TBD: start]] → [[TBD: end]] |
| Total project spend (tagged) | [[TBD: $]] |
| Dev box (shared EC2, untagged) | [[TBD: $]] |
| Monthly budget | $300.00 |
| Budget used this month | [[TBD: %]] |
| Kilometres processed (from the register) | [[TBD: km]] |
| **Cost per km processed** (processing services only) | [[TBD: $/km]] |
| Target cost per km (proposal) | < $0.02 |
<!-- COST-SUMMARY:END -->

## Spend by AWS service

<!-- COST-BY-SERVICE:BEGIN -->
| AWS service | What it is used for | Spend to date |
|---|---|---|
| [[TBD: generated rows]] | | |
<!-- COST-BY-SERVICE:END -->

![Cost by service](assets/cost_by_service.png)

## Spend by phase

<!-- COST-BY-PHASE:BEGIN -->
| Phase | Spend |
|---|---|
| [[TBD: generated rows]] | |
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
