"""Regenerate docs/midpoint/02-COST-REPORT.md from AWS Cost Explorer.

- Project spend: resources tagged Project=patchwork, grouped by service and by Phase tag.
- If the cost-allocation tag is not active yet (first ~24 h), falls back to the account-wide view and says so.
- Kilometres processed are read from eval/results/km_processed.json (written by the pipeline) to give cost/km.
- Also writes docs/midpoint/assets/cost.csv and cost_by_service.png.

Usage:  make cost-report   [--start 2026-10-12] [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "midpoint" / "02-COST-REPORT.md"
ASSETS = ROOT / "docs" / "midpoint" / "assets"
KM_FILE = ROOT / "eval" / "results" / "km_processed.json"
PROJECT_START = "2026-10-12"
BUDGET_USD = 300.0
# Services whose cost scales with km processed (training, agent dev and the dev box are excluded).
PROCESSING_SERVICES = {
    "AWS Batch",
    "Amazon Elastic Compute Cloud - Compute",
    "Amazon Simple Storage Service",
    "AWS Step Functions",
    "AWS Lambda",
    "Amazon Relational Database Service",
    "Amazon DynamoDB",
    "Amazon Simple Queue Service",
    "Amazon EventBridge",
    "Amazon Location Service",
}
PURPOSE = {
    "Amazon SageMaker": "Segmentation model training (GPU Spot)",
    "AWS Batch": "OpenCV 5 perception jobs",
    "Amazon Elastic Compute Cloud - Compute": "Batch Graviton Spot instances (and dev box if untagged)",
    "EC2 - Other": "EBS volumes, data transfer",
    "Amazon Simple Storage Service": "Clips, crops, overlays, models, state",
    "Amazon Relational Database Service": "Aurora Serverless v2 PostGIS register",
    "Amazon DynamoDB": "Job state, idempotency, approval tokens",
    "AWS Step Functions": "Pipeline orchestration + approval gate",
    "AWS Lambda": "Register loader, viewer API, agent tools",
    "Amazon Bedrock": "Claude for the agent",
    "Amazon Bedrock AgentCore": "Agent runtime / gateway / memory",
    "Amazon CloudFront": "Map viewer delivery",
    "Amazon API Gateway": "Viewer / console API",
    "Amazon Location Service": "Map tiles, snap-to-road",
    "AmazonCloudWatch": "Metrics, logs, dashboard",
    "AWS Key Management Service": "Encryption keys",
    "AWS Secrets Manager": "Database credentials",
    "Amazon Elastic Container Registry (ECR)": "Pipeline container images",
    "Amazon Simple Queue Service": "Ingest queue + DLQ",
    "Amazon EventBridge": "S3 upload events",
    "AWS Budgets": "Budget alerts",
    "AWS Cost Explorer": "Cost API queries ($0.01 each)",
    "Amazon Virtual Private Cloud": "Networking (no NAT)",
}


def replace_block(text: str, name: str, body: str) -> str:
    pat = re.compile(rf"(<!-- {name}:BEGIN -->\n).*?(\n<!-- {name}:END -->)", re.S)
    if not pat.search(text):
        raise SystemExit(f"marker {name} missing in {REPORT}")
    return pat.sub(lambda m: m.group(1) + body.rstrip("\n") + m.group(2), text)


def fetch(ce, start: str, end: str, group_key: str, group_type: str, tag_filter: bool) -> dict[str, float]:
    kwargs = dict(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": group_type, "Key": group_key}],
    )
    # gross usage only: credits are reported separately (otherwise every service nets to ~$0)
    usage = {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}}
    if tag_filter:
        tag = {"Tags": {"Key": "Project", "Values": ["patchwork"], "MatchOptions": ["EQUALS"]}}
        kwargs["Filter"] = {"And": [usage, tag]}
    else:
        kwargs["Filter"] = usage
    out: dict[str, float] = {}
    token = None
    while True:
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_cost_and_usage(**kwargs)
        for period in resp["ResultsByTime"]:
            for g in period["Groups"]:
                key = g["Keys"][0]
                out[key] = out.get(key, 0.0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        token = resp.get("NextPageToken")
        if not token:
            return out


def by_record_type(ce, start: str, end: str) -> dict[str, float]:
    """Account-wide Usage / Credit / Tax / ... totals; net = sum (what is actually paid)."""
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
    )
    out: dict[str, float] = {}
    for p in resp["ResultsByTime"]:
        for g in p["Groups"]:
            out[g["Keys"][0]] = out.get(g["Keys"][0], 0.0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
    return out


def write_chart_and_csv(rows: list[tuple[str, float]]) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    with open(ASSETS / "cost.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["service", "usd"])
        w.writerows((s, f"{v:.4f}") for s, v in rows)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    top = [r for r in rows if r[1] >= 0.005][:12]
    if not top:
        return
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(top) + 1.2))
    ax.barh([s for s, _ in reversed(top)], [v for _, v in reversed(top)], color="#2a6f97")
    ax.set_xlabel("USD")
    ax.set_title("Patchwork spend by AWS service")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(ASSETS / "cost_by_service.png", dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=PROJECT_START)
    ap.add_argument("--end", default=(dt.date.today() + dt.timedelta(days=1)).isoformat())
    args = ap.parse_args()

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

        ce = boto3.client("ce", region_name="us-east-1")  # Cost Explorer endpoint is global (us-east-1)
        tagged = fetch(ce, args.start, args.end, "SERVICE", "DIMENSION", tag_filter=True)
        note = "Filtered by cost-allocation tag `Project=patchwork`."
        if not tagged:
            tagged = fetch(ce, args.start, args.end, "SERVICE", "DIMENSION", tag_filter=False)
            note = (
                "⚠️ The `Project` cost-allocation tag is not active yet (or has no data), so this shows the "
                "**whole account**, including the dev box and anything unrelated."
            )
        by_phase = fetch(ce, args.start, args.end, "Phase", "TAG", tag_filter=True)
        today = dt.date.today()
        mtd = by_record_type(ce, today.replace(day=1).isoformat(), (today + dt.timedelta(days=1)).isoformat())
        since = by_record_type(ce, args.start, args.end)
    except NoCredentialsError:
        print("No AWS credentials (attach the instance role first). Report left unchanged.", file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as e:
        print(f"Cost Explorer call failed: {e}", file=sys.stderr)
        return 2

    rows = sorted(((s, v) for s, v in tagged.items() if v > 0), key=lambda r: -r[1])
    total = sum(v for _, v in rows)
    processing = sum(v for s, v in rows if s in PROCESSING_SERVICES)
    km = json.loads(KM_FILE.read_text()).get("km", 0.0) if KM_FILE.exists() else 0.0
    cost_per_km = f"${processing / km:.4f}/km" if km > 0 else "n/a (no km processed yet)"

    summary = "\n".join(
        [
            "| Item | Value |",
            "|---|---|",
            f"| Period | {args.start} → {args.end} (end exclusive) |",
            f"| Project usage (gross, before credits) | **${total:,.2f}** |",
            f"| Account usage since project start (gross) | ${since.get('Usage', 0):,.2f} |",
            f"| Paid by AWS promotional credits | ${-since.get('Credit', 0):,.2f} |",
            f"| **Real money paid (net after credits)** | **${sum(since.values()):,.2f}** "
            f"(guarded by the `patchwork-real-spend` budget: alert at $0.01) |",
            "| Dev box (shared EC2 t3a.xlarge, us-east-1) | included above only if it is tagged |",
            f"| Planned monthly usage (from credits) | ${BUDGET_USD:,.2f} |",
            f"| Account usage this month to date | ${mtd.get('Usage', 0):,.2f} "
            f"({mtd.get('Usage', 0) / BUDGET_USD * 100:.1f}% of plan); net paid ${sum(mtd.values()):,.2f} |",
            f"| Kilometres processed (from the register) | {km:,.1f} |",
            f"| **Cost per km processed** (processing services only) | {cost_per_km} |",
            "| Target cost per km (proposal) | < $0.02 |",
            f"| Generated | {dt.datetime.now(dt.UTC).strftime('%Y-%m-%d %H:%M UTC')} by `make cost-report` |",
            "",
            note,
        ]
    )
    svc = ["| AWS service | What it is used for | Usage to date (gross, paid by credits) |", "|---|---|---|"]
    svc += [f"| {s} | {PURPOSE.get(s, '')} | ${v:,.2f} |" for s, v in rows] or ["| (no spend yet) | | $0.00 |"]
    phase_rows = sorted((k.split("$", 1)[-1] or "(untagged)", v) for k, v in by_phase.items() if v > 0)
    ph = ["| Phase | Spend |", "|---|---|"]
    ph += [f"| {k} | ${v:,.2f} |" for k, v in phase_rows] or ["| (no tagged spend yet) | $0.00 |"]

    text = REPORT.read_text()
    text = replace_block(text, "COST-SUMMARY", summary)
    text = replace_block(text, "COST-BY-SERVICE", "\n".join(svc))
    text = replace_block(text, "COST-BY-PHASE", "\n".join(ph))
    REPORT.write_text(text)
    write_chart_and_csv(rows)
    print(f"Updated {REPORT.relative_to(ROOT)}: total ${total:.2f}, {len(rows)} services, km={km}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
