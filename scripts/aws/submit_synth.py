"""Submit the synthetic-survey render as one AWS Batch array job (one child per clip), decision D-13.

  uv run python scripts/aws/submit_synth.py --passes 1,2,3 [--seed 7] [--clip-m 3000] [--wait]
Download afterwards:  aws s3 sync s3://<datasets>/synth/seed07 data/synth/seed07
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import boto3

from patchwork.pipeline.synth_job import n_clips
from patchwork.synth.corridor import load_corridor

ROOT = Path(__file__).resolve().parents[2]
REGION = "ap-south-1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", default="1,2,3")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clip-m", type=float, default=3000.0)
    ap.add_argument("--queue", default="patchwork-spot")
    ap.add_argument("--definition", default="patchwork-synth-render")
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()

    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    bucket = f"patchwork-{account}-datasets"
    per_pass = n_clips(load_corridor(ROOT / "data" / "corridor").length_m, args.clip_m)
    size = per_pass * len(args.passes.split(","))
    batch = boto3.client("batch", region_name=REGION)
    cmd = ["patchwork.pipeline.synth_job", "--bucket", bucket, "--prefix", "synth", "--seed", str(args.seed)]
    cmd += ["--passes", args.passes, "--clip-m", str(args.clip_m)]
    job = batch.submit_job(
        jobName=f"synth-seed{args.seed:02d}-p{args.passes.replace(',', '')}",
        jobQueue=args.queue,
        jobDefinition=args.definition,
        arrayProperties={"size": size},
        containerOverrides={"command": cmd},
        tags={"Project": "patchwork", "Phase": "1"},
        propagateTags=True,
    )
    jid = job["jobId"]
    print(f"submitted {jid}: {size} children -> s3://{bucket}/synth/seed{args.seed:02d}/")
    t0 = time.time()
    while args.wait:
        j = batch.describe_jobs(jobs=[jid])["jobs"][0]
        summary = j.get("arrayProperties", {}).get("statusSummary", {})
        print(f"{(time.time() - t0) / 60:5.1f} min  {j['status']:10s} {summary}", flush=True)
        if j["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
