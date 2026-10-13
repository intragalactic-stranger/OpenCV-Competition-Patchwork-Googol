"""Upload a survey pass to the raw bucket the way a capture app would, which starts the cloud pipeline.

  uv run python scripts/aws/upload_pass.py --seed 11 --pass 1 --model seg-v1 [--run demo-01]

Synthetic passes are copied server-side from the datasets bucket. Ground truth never goes to the raw bucket:
  - truth/ is not copied
  - frames.csv is reduced to the columns a dashcam records (frame index, timestamp)
manifest.json is written LAST; its creation fires EventBridge -> Step Functions (one execution per pass).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json

import boto3

REGION = "ap-south-1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--pass", dest="pass_k", type=int, default=1)
    ap.add_argument("--model", default="seg-v1")
    ap.add_argument("--run", default=None)
    ap.add_argument("--clips", default=None, help="comma list of clip numbers (default: all)")
    args = ap.parse_args()
    acct = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    ds, raw = f"patchwork-{acct}-datasets", f"patchwork-{acct}-raw"
    run = args.run or f"run-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}"
    s3 = boto3.client("s3", region_name=REGION)
    src = f"synth/seed{args.seed:02d}/pass_{args.pass_k}"
    dst = f"{run}/pass_{args.pass_k}"
    resp = s3.list_objects_v2(Bucket=ds, Prefix=f"{src}/clip_", Delimiter="/")
    clips = sorted(p["Prefix"].rstrip("/").split("/")[-1] for p in resp.get("CommonPrefixes", []))
    if args.clips:
        keep = {f"clip_{int(c):02d}" for c in args.clips.split(",")}
        clips = [c for c in clips if c in keep]
    for c in clips:
        for f in ("clip.mp4", "gnss.csv", "imu.csv", "meta.json"):
            s3.copy({"Bucket": ds, "Key": f"{src}/{c}/{f}"}, raw, f"{dst}/{c}/{f}")
        body = s3.get_object(Bucket=ds, Key=f"{src}/{c}/frames.csv")["Body"].read().decode()
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["frame", "t"])
        for r in csv.DictReader(io.StringIO(body)):
            w.writerow([r["frame"], r["t"]])
        s3.put_object(Bucket=raw, Key=f"{dst}/{c}/frames.csv", Body=out.getvalue().encode())
        print(f"uploaded {c}", flush=True)
    manifest = {
        "run_id": run,
        "pass": f"pass_{args.pass_k}",
        "n_clips": len(clips),
        "model": args.model,
        "source": f"synthetic survey, seed {args.seed}, pass {args.pass_k}",
        "uploaded": dt.datetime.now(dt.UTC).isoformat(),
    }
    s3.put_object(Bucket=raw, Key=f"{dst}/manifest.json", Body=json.dumps(manifest).encode())
    print(f"manifest written: s3://{raw}/{dst}/manifest.json -> pipeline started")


if __name__ == "__main__":
    main()
