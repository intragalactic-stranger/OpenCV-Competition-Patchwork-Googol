"""SageMaker entry point (GPU training, decision D-31). Runs inside the AWS PyTorch training container.

SageMaker gives us: the prepared dataset at /opt/ml/input/data/train, a checkpoint folder /opt/ml/checkpoints that it
mirrors to S3 (a restarted Spot job finds last.pt there and resumes), and the hyperparameters as CLI flags.
At the end the model files are copied to s3://<artifacts>/models/<version>/, the same layout as the Batch CPU jobs.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PIP = [
    "transformers==4.57.6",
    "opencv-contrib-python-headless==5.0.0.93",
    "onnx==1.23.2",
    "onnxruntime==1.31.0",
    "pydantic>=2.7",
    "shapely>=2.0",
    "pyproj>=3.6",
    "pyyaml>=6.0",
    "python-ulid>=2.7",
    "networkx>=3.3",
    "fsspec>=2024.6",
]
CKPT = Path("/opt/ml/checkpoints")
DATA = Path("/opt/ml/input/data/train")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--artifacts-bucket", required=True)
    ap.add_argument("--backbone", default="nvidia/mit-b2")
    ap.add_argument("--epochs", default="20")
    ap.add_argument("--batch", default="24")
    ap.add_argument("--lr", default="2e-4")
    ap.add_argument("--max-hours", default="3.5")
    ap.add_argument("--limit", default="")
    ap.add_argument("--init", default="")
    args, _ = ap.parse_known_args()

    # one OpenCV only: the container may ship opencv-python 4.x, which would shadow OpenCV 5
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "-y",
            "-q",
            "opencv-python",
            "opencv-python-headless",
            "opencv-contrib-python",
        ],
        check=False,
    )
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PIP], check=True)

    cmd = [
        sys.executable,
        "-m",
        "training.train",
        "--data",
        str(DATA),
        "--out",
        str(CKPT),
        "--backbone",
        args.backbone,
        "--epochs",
        args.epochs,
        "--batch",
        args.batch,
        "--lr",
        args.lr,
        "--max-hours",
        args.max_hours,
        "--workers",
        "6",
        "--threads",
        "2",
        "--skip-opencv-eval",
    ]
    if args.limit:
        cmd += ["--limit", args.limit]
    if args.init:
        cmd += ["--init", args.init]
    subprocess.run(cmd, check=True)

    import boto3

    s3 = boto3.client("s3")
    for f in sorted(CKPT.iterdir()):
        if f.is_file() and f.name not in {"last.pt", "init.pt"}:
            s3.upload_file(str(f), args.artifacts_bucket, f"models/{args.version}/{f.name}")
            print(f"uploaded s3://{args.artifacts_bucket}/models/{args.version}/{f.name}", flush=True)


if __name__ == "__main__":
    main()
