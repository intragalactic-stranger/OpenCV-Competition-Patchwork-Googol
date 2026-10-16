"""Batch job: score a trained model through OpenCV 5 (the deployed runtime) on Graviton CPU.

GPU training jobs skip this slow CPU step (--skip-opencv-eval); this job fills it in afterwards, S3 to S3:
dataset + model.onnx down, `training.evaluate` + `training.parity` run, eval_opencv.json + parity.json up.

  python -m training.evaluate_job --model-uri s3://<artifacts>/models/seg-v4 --data-uri s3://<datasets>/train/v3
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from training.evaluate import evaluate_onnx
from training.parity import run_parity


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-uri", required=True)
    ap.add_argument("--data-uri", required=True)
    ap.add_argument("--work", type=Path, default=Path("/tmp/eval"))
    args = ap.parse_args()
    data, model = args.work / "data", args.work / "model"
    model.mkdir(parents=True, exist_ok=True)
    subprocess.run(["aws", "s3", "sync", args.data_uri, str(data), "--only-show-errors"], check=True)
    subprocess.run(
        ["aws", "s3", "cp", f"{args.model_uri}/model.onnx", str(model / "model.onnx"), "--only-show-errors"], check=True
    )
    res = evaluate_onnx(model / "model.onnx", data)
    (model / "eval_opencv.json").write_text(json.dumps(res, indent=1))
    run_parity(model / "model.onnx", data)  # writes model/parity.json
    for f in ("eval_opencv.json", "parity.json"):
        subprocess.run(["aws", "s3", "cp", str(model / f), f"{args.model_uri}/{f}", "--only-show-errors"], check=True)
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
