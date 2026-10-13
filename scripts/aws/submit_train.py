"""Submit dataset preparation + CPU training on AWS Batch (Graviton Spot; decision D-25, no GPU).

  uv run python scripts/aws/submit_train.py --version seg-v1 [--arch segformer] [--epochs 12] [--skip-prepare]

1. prepare  (4 vCPU): sync seed-07 synthetic passes + prepared Pothole Mix from S3 -> training/prepare.py
                      -> s3://<datasets>/train/<data-version>/
2. train-cpu (32 vCPU, depends on 1): training/train.py -> s3://<artifacts>/models/<version>/
   (model.onnx, metrics.json, parity.json, eval_opencv.json; checkpoints for Spot resume)
Then: uv run python -m training.model_card s3://<artifacts>/models/<version>
"""

from __future__ import annotations

import argparse

import boto3

REGION = "ap-south-1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="model version, e.g. seg-v1")
    ap.add_argument("--data-version", default="v1")
    ap.add_argument("--arch", choices=["segformer", "lraspp"], default="segformer")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--max-hours", type=float, default=6.0)
    ap.add_argument("--seed-dir", default="synth/seed07")
    ap.add_argument("--skip-prepare", action="store_true")
    ap.add_argument("--queue", default="patchwork-spot")
    args = ap.parse_args()

    acct = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    ds, art = f"s3://patchwork-{acct}-datasets", f"s3://patchwork-{acct}-artifacts"
    batch = boto3.client("batch", region_name=REGION)
    tags = {"Project": "patchwork", "Phase": "3"}
    depends = []
    data_s3 = f"{ds}/train/{args.data_version}"
    if not args.skip_prepare:
        prep = batch.submit_job(
            jobName=f"prepare-{args.data_version}",
            jobQueue=args.queue,
            jobDefinition="patchwork-prepare",
            containerOverrides={
                "command": [
                    "training.prepare_job",
                    "--synth",
                    f"{ds}/{args.seed_dir}",
                    "--merge",
                    f"{ds}/train/pmix_only",
                    "--out",
                    data_s3,
                ]
            },
            tags=tags,
            propagateTags=True,
        )
        print(f"prepare: {prep['jobId']} -> {data_s3}")
        depends = [{"jobId": prep["jobId"]}]
    cmd = [
        "training.train",
        "--data",
        "/work/data",
        "--data-s3",
        data_s3,
        "--out",
        "/work/run",
        "--s3-out",
        f"{art}/models/{args.version}",
        "--arch",
        args.arch,
        "--epochs",
        str(args.epochs),
        "--max-hours",
        str(args.max_hours),
        "--workers",
        "6",
        "--threads",
        "26",
    ]
    job = batch.submit_job(
        jobName=f"train-{args.version}",
        jobQueue=args.queue,
        jobDefinition="patchwork-train-cpu",
        dependsOn=depends,
        containerOverrides={"command": cmd},
        tags=tags,
        propagateTags=True,
    )
    print(f"train: {job['jobId']} -> {art}/models/{args.version}")


if __name__ == "__main__":
    main()
