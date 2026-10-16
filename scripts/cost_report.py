"""Regenerate main_docs/midpoint/02-COST-REPORT.md from AWS Cost Explorer.

- Project spend: resources tagged Project=patchwork, grouped by service and by Phase tag.
- If the cost-allocation tag is not active yet (first ~24 h), falls back to the account-wide view and says so.
- Kilometres processed are read from eval/results/km_processed.json (written by the pipeline) to give cost/km.
- Also writes main_docs/midpoint/assets/cost.csv and cost_by_service.png.

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
REPORT = ROOT / "main_docs" / "midpoint" / "02-COST-REPORT.md"
ASSETS = ROOT / "main_docs" / "midpoint" / "assets"
E2E_FILE = ROOT / "eval" / "results" / "end_to_end.json"
PERCEIVE_VCPU = 4  # patchwork-perceive job definition
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
    "Amazon Bedrock": "Amazon Nova for the agent",
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


def credit_coverage(ce, start: str, end: str) -> dict[str, dict[str, float]]:
    """Account-wide, per service: usage, credits applied, net. Net > 0 means credits did NOT cover it."""
    out: dict[str, dict[str, float]] = {}
    kwargs = dict(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
    )
    token = None
    while True:
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_cost_and_usage(**kwargs)
        for p in resp["ResultsByTime"]:
            for g in p["Groups"]:
                svc, rt = g["Keys"]
                d = out.setdefault(svc, {})
                d[rt] = d.get(rt, 0.0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
        token = resp.get("NextPageToken")
        if not token:
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
        coverage = credit_coverage(ce, args.start, args.end)
    except NoCredentialsError:
        print("No AWS credentials (attach the instance role first). Report left unchanged.", file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as e:
        print(f"Cost Explorer call failed: {e}", file=sys.stderr)
        return 2

    rows = sorted(((s, v) for s, v in tagged.items() if v > 0), key=lambda r: -r[1])
    total = sum(v for _, v in rows)
    processing = sum(v for s, v in rows if s in PROCESSING_SERVICES)
    passes = json.loads(E2E_FILE.read_text())["passes"] if E2E_FILE.exists() else []
    km = sum(p["km"] for p in passes)
    cost_per_km = f"${processing / km:.4f}/km" if km > 0 else "n/a (no km processed yet)"
    measured_per_km = "n/a (no pipeline run evaluated yet)"
    if km > 0:
        sec_per_km = sum(p["seconds_per_km"] * p["km"] for p in passes) / km
        prices = boto3.client("ec2", region_name="ap-south-1").describe_spot_price_history(
            InstanceTypes=["c8g.4xlarge", "c7g.4xlarge"],
            ProductDescriptions=["Linux/UNIX"],
            StartTime=dt.datetime.now(dt.UTC),
        )["SpotPriceHistory"]
        vcpu_h = sum(float(x["SpotPrice"]) for x in prices) / len(prices) / 16
        usd_km = sec_per_km / 3600 * PERCEIVE_VCPU * vcpu_h
        (ROOT / "eval" / "results" / "cost_per_km.json").write_text(
            json.dumps(
                {
                    "usd_per_km": round(usd_km, 5),
                    "seconds_per_km": round(sec_per_km, 1),
                    "vcpu": PERCEIVE_VCPU,
                    "spot_usd_per_vcpu_h": round(vcpu_h, 5),
                    "upper_bound_usd_per_km": round(processing / km, 4),
                    "km": round(km, 2),
                }
            )
        )
        measured_per_km = (
            f"**${usd_km:.4f}/km** ({sec_per_km:.0f} s of {PERCEIVE_VCPU}-vCPU "
            f"Graviton Spot per km at ${vcpu_h:.4f}/vCPU-h, current Spot price)"
        )

    net_mtd = round(sum(mtd.values()), 2) + 0.0  # + 0.0 turns -0.0 into 0.0
    summary = "\n".join(
        [
            "| Item | Value |",
            "|---|---|",
            f"| Period | {args.start} → {args.end} (end exclusive) |",
            f"| Project usage (gross, before credits) | **${total:,.2f}** |",
            f"| Account usage since project start (gross) | ${since.get('Usage', 0):,.2f} |",
            f"| Paid by AWS promotional credits | ${-since.get('Credit', 0):,.2f} |",
            f"| **Real money paid (net after credits)** | **${round(sum(since.values()), 2) + 0.0:,.2f}** "
            f"(guarded by the `patchwork-real-spend` budget: alert at $0.01) |",
            "| Dev box (shared EC2 t3a.xlarge, us-east-1) | included above only if it is tagged |",
            f"| Planned monthly usage (from credits) | ${BUDGET_USD:,.2f} |",
            f"| Account usage this month to date | ${mtd.get('Usage', 0):,.2f} "
            f"({mtd.get('Usage', 0) / BUDGET_USD * 100:.1f}% of plan); net paid ${net_mtd:,.2f} |",
            f"| Kilometres processed (pipeline runs evaluated in `eval/results/end_to_end.json`) | {km:,.1f} |",
            f"| Perception compute cost per km (measured run time × Spot price) | {measured_per_km} |",
            f"| Upper bound: all processing-service spend ÷ km (also includes data rendering and training) "
            f"| {cost_per_km} |",
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

    cov = ["| AWS service | Usage | Paid by credits | Real money (net) | Covered? |", "|---|---|---|---|---|"]
    uncovered = []
    # Cost Explorer books the credit for inter-region data transfer (e.g. S3 in Mumbai -> dev box in us-east-1)
    # under "AWS Data Transfer", while the usage stays under S3 / EC2. Let that credit pay those shortfalls first.
    pool = -coverage.get("AWS Data Transfer", {}).get("Credit", 0.0) - coverage.get("AWS Data Transfer", {}).get(
        "Usage", 0.0
    )
    for name, d in sorted(coverage.items(), key=lambda kv: -kv[1].get("Usage", 0.0)):
        usage, credit = d.get("Usage", 0.0), d.get("Credit", 0.0)
        net = sum(d.values())
        if usage < 0.00005 and net < 0.00005:
            continue
        via_transfer = min(max(net, 0.0), max(pool, 0.0)) if name != "AWS Data Transfer" else 0.0
        pool -= via_transfer
        net -= via_transfer
        ok = net <= 0.005
        if not ok:
            uncovered.append(name)
        note = f" (incl. ${via_transfer:,.4f} data-transfer credit)" if via_transfer > 0.00005 else ""
        cov.append(
            f"| {name} | ${usage:,.4f} | ${-credit + via_transfer:,.4f}{note} | ${net:,.4f} | "
            f"{'✅' if ok else '⚠️ NOT covered: stop using it'} |"
        )
    if len(cov) == 2:
        cov.append("| (no usage yet) | | | | |")
    cov.append("")
    cov.append(
        "**All services fully covered by promotional credits.**"
        if not uncovered
        else f"⚠️ **Real charges detected for: {', '.join(uncovered)}.** Stop these services or find an alternative "
        "(decision D-27)."
    )

    text = REPORT.read_text()
    text = replace_block(text, "COST-CREDIT-COVERAGE", "\n".join(cov))
    text = replace_block(text, "COST-SUMMARY", summary)
    text = replace_block(text, "COST-BY-SERVICE", "\n".join(svc))
    text = replace_block(text, "COST-BY-PHASE", "\n".join(ph))
    REPORT.write_text(text)
    write_chart_and_csv(rows)
    print(f"Updated {REPORT.relative_to(ROOT)}: total ${total:.2f}, {len(rows)} services, km={km}")
    if uncovered:
        print(f"WARNING: real (uncovered) charges for {uncovered}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
