"""Figure of one pipeline execution, drawn from the Step Functions execution history (no console screenshot).

  uv run python scripts/figures/sfn_run.py [--execution ARN]   (default: latest SUCCEEDED execution)
Writes docs/midpoint/assets/sfn_run.png: the state graph with each state's duration and status, plus the Batch
array children's durations.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import boto3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REGION = "ap-south-1"
SM = "arn:aws:states:ap-south-1:{acct}:stateMachine:patchwork-process-pass"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execution", default=None)
    args = ap.parse_args()
    sfn = boto3.client("stepfunctions", region_name=REGION)
    acct = boto3.client("sts").get_caller_identity()["Account"]
    arn = args.execution or next(
        e["executionArn"]
        for e in sfn.list_executions(stateMachineArn=SM.format(acct=acct), statusFilter="SUCCEEDED")["executions"]
    )
    ex = sfn.describe_execution(executionArn=arn)
    hist = sfn.get_execution_history(executionArn=arn, maxResults=1000)["events"]
    t0 = ex["startDate"]
    spans, open_ = [], {}
    for e in hist:
        if e["type"].endswith("StateEntered"):
            open_[e["stateEnteredEventDetails"]["name"]] = e["timestamp"]
        elif e["type"].endswith("StateExited"):
            n = e["stateExitedEventDetails"]["name"]
            spans.append((n, (open_.pop(n) - t0).total_seconds(), (e["timestamp"] - t0).total_seconds()))
    # Batch array children of the perceive step
    batch = boto3.client("batch", region_name=REGION)
    jobs = []
    for e in hist:
        if e["type"] == "TaskSubmitted" and "JobId" in e["taskSubmittedEventDetails"].get("output", ""):
            import json

            jid = json.loads(e["taskSubmittedEventDetails"]["output"])["JobId"]
            j = batch.describe_jobs(jobs=[jid])["jobs"][0]
            if j.get("arrayProperties", {}).get("size"):
                kids = batch.list_jobs(arrayJobId=jid, jobStatus="SUCCEEDED")["jobSummaryList"]
                for k in sorted(kids, key=lambda k: k["arrayProperties"]["index"]):
                    jobs.append(
                        (
                            f"perceive[{k['arrayProperties']['index']}]",
                            (k["startedAt"] / 1000 - t0.timestamp()),
                            (k["stoppedAt"] / 1000 - t0.timestamp()),
                        )
                    )
    rows = spans + jobs
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(rows) + 1.4))
    colors = {"ReadManifest": "#8aa1b1", "Perceive": "#2a6f97", "Assemble": "#468faf"}
    for i, (name, a, b) in enumerate(rows):
        c = colors.get(name, "#a9d6e5")
        ax.barh(i, (b - a) / 60, left=a / 60, color=c)
        ax.text(b / 60 + 0.1, i, f"{name}  {(b - a) / 60:.1f} min", va="center", fontsize=9)
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.set_xlabel("minutes since upload (manifest.json)")
    total = (ex["stopDate"] - t0).total_seconds() / 60
    ax.set_title(
        f"Step Functions patchwork-process-pass · {ex['status']} in {total:.1f} min\n{ex['name']}", fontsize=10
    )
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    out = ROOT / "docs" / "midpoint" / "assets" / "sfn_run.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out} ({len(rows)} bars, {total:.1f} min)")


if __name__ == "__main__":
    main()
