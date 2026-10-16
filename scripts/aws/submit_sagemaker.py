"""Launch a GPU training job on SageMaker (decision D-31): SegFormer on the prepared set, AWS PyTorch container.

Cost guard: one instance, on-demand price known in advance, hard MaxRuntime. Nothing keeps running after the job.

  uv run python scripts/aws/submit_sagemaker.py --version seg-v4-trial --limit 64 --epochs 1 --max-runtime-min 25
  uv run python scripts/aws/submit_sagemaker.py --version seg-v4 --backbone nvidia/mit-b2 --epochs 20
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
REGION = "ap-south-1"
IMAGE = "763104351884.dkr.ecr.ap-south-1.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker"


def tf_output(name: str) -> str:
    out = subprocess.run(
        ["terraform", "output", "-json", name],
        cwd=ROOT / "infra/terraform/envs/dev",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def source_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for src, arc in ((ROOT / "training", "training"), (ROOT / "src" / "patchwork", "patchwork")):
            tar.add(src, arc, filter=lambda t: None if "__pycache__" in t.name else t)
        tar.add(ROOT / "training" / "sm_entry.py", "sm_entry.py")
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--data-version", default="v3")
    ap.add_argument("--backbone", default="nvidia/mit-b2")
    ap.add_argument("--epochs", default="20")
    ap.add_argument("--batch", default="24")
    ap.add_argument("--lr", default="2e-4")
    ap.add_argument("--limit", default="")
    ap.add_argument("--init", default="")
    ap.add_argument("--arch", default="segformer", choices=["segformer", "lraspp"])
    ap.add_argument("--synthetic-only", action="store_true", help="licence-clean model (D-07)")
    ap.add_argument("--instance", default="ml.g5.2xlarge")
    ap.add_argument("--max-runtime-min", type=int, default=240)
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()

    buckets = tf_output("buckets")
    role = tf_output("sagemaker_role_arn")
    art, ds = buckets["artifacts"], buckets["datasets"]
    key = f"sagemaker/source/{args.version}.tar.gz"
    boto3.client("s3", region_name=REGION).put_object(Bucket=art, Key=key, Body=source_tarball())

    sm = boto3.client("sagemaker", region_name=REGION)
    job = f"patchwork-{args.version}-{time.strftime('%m%d-%H%M%S')}"
    max_hours = max(args.max_runtime_min / 60 - 0.5, 0.2)  # leave time for ONNX export, parity and upload
    hp = {
        "sagemaker_program": "sm_entry.py",
        "sagemaker_submit_directory": f"s3://{art}/{key}",
        "version": args.version,
        "artifacts-bucket": art,
        "backbone": args.backbone,
        "epochs": args.epochs,
        "batch": args.batch,
        "lr": args.lr,
        "max-hours": f"{max_hours:.2f}",
    }
    if args.limit:
        hp["limit"] = args.limit
    if args.init:
        hp["init"] = args.init
    hp["arch"] = args.arch
    if args.synthetic_only:
        hp["synthetic-only"] = "1"
    sm.create_training_job(
        TrainingJobName=job,
        AlgorithmSpecification={"TrainingImage": IMAGE, "TrainingInputMode": "File"},
        RoleArn=role,
        HyperParameters=hp,
        InputDataConfig=[
            {
                "ChannelName": "train",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": f"s3://{ds}/train/{args.data_version}/",
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
            }
        ],
        OutputDataConfig={"S3OutputPath": f"s3://{art}/sagemaker/output/"},
        CheckpointConfig={
            "S3Uri": f"s3://{art}/models/{args.version}/checkpoints/",
            "LocalPath": "/opt/ml/checkpoints",
        },
        ResourceConfig={"InstanceType": args.instance, "InstanceCount": 1, "VolumeSizeInGB": 50},
        StoppingCondition={"MaxRuntimeInSeconds": args.max_runtime_min * 60},
        Tags=[{"Key": k, "Value": v} for k, v in (("Project", "patchwork"), ("Phase", "6"), ("Owner", "googol"))],
    )
    print(f"started {job}  ({args.instance}, max {args.max_runtime_min} min)")
    while args.wait:
        d = sm.describe_training_job(TrainingJobName=job)
        print(time.strftime("%H:%M:%S"), d["TrainingJobStatus"], d.get("SecondaryStatus"), flush=True)
        if d["TrainingJobStatus"] in ("Completed", "Failed", "Stopped"):
            print(d.get("FailureReason", ""), "billable s:", d.get("BillableTimeInSeconds"))
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
