"""AWS Batch entry points for the cloud pipeline (orchestrated by Step Functions, see infra/terraform/modules/pipeline).

  perceive  (array job, one child per clip, parallel):
      s3://<raw>/<run>/<pass>/clip_NN/{clip.mp4,frames.csv,gnss.csv,meta.json} + model
      -> s3://<artifacts>/runs/<run>/<pass>/clip_NN/perception.json
  assemble  (one job per pass, sequential and cheap):
      perception.json of every clip -> localise (route-progress hint) -> defects.json + evidence images
      -> register (Aurora via Data API, idempotent) -> map viewer (S3 + CloudFront)

The clip's frames.csv carries truth columns for synthetic data; the pipeline reads only its timestamps.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import boto3

from patchwork.pipeline.publish import publish
from patchwork.pipeline.runner import ClipRunner, assemble_pass, save_perception
from patchwork.register.dataapi import Register
from patchwork.synth.corridor import load_corridor

ROOT = Path(__file__).resolve().parents[3]
REGION = "ap-south-1"
CALIB = ROOT / "data" / "calib" / "cam01-v1.json"
CLIP_FILES = ("clip.mp4", "frames.csv", "gnss.csv", "meta.json")


def emf(metrics: dict[str, float], dims: dict[str, str], unit: dict[str, str] | None = None) -> None:
    """CloudWatch Embedded Metric Format on stdout: the awslogs driver turns it into metrics (namespace Patchwork)."""
    import time as _t

    unit = unit or {}
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(_t.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Patchwork",
                            "Dimensions": [list(dims)],
                            "Metrics": [{"Name": k, "Unit": unit.get(k, "None")} for k in metrics],
                        }
                    ],
                },
                **dims,
                **metrics,
            }
        ),
        flush=True,
    )


def split(uri: str) -> tuple[str, str]:
    b, _, k = uri.removeprefix("s3://").partition("/")
    return b, k.rstrip("/")


def download(s3, uri: str, dst: Path) -> Path:
    b, k = split(uri)
    dst.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(b, k, str(dst))
    return dst


def upload_tree(s3, src: Path, uri: str) -> int:
    b, k = split(uri)
    n = 0
    for p in sorted(src.rglob("*")):
        if p.is_file():
            s3.upload_file(str(p), b, f"{k}/{p.relative_to(src).as_posix()}")
            n += 1
    return n


def list_clips(s3, pass_uri: str) -> list[str]:
    b, k = split(pass_uri)
    resp = s3.list_objects_v2(Bucket=b, Prefix=f"{k}/clip_", Delimiter="/")
    return sorted(p["Prefix"].rstrip("/").split("/")[-1] for p in resp.get("CommonPrefixes", []))


def cmd_perceive(args, s3, work: Path) -> None:
    clips = list_clips(s3, args.pass_uri)
    index = args.index if args.index is not None else int(os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX", "0"))
    clip = clips[index]
    pass_name = split(args.pass_uri)[1].split("/")[-1]
    clip_dir = work / pass_name / clip
    for f in CLIP_FILES:
        download(s3, f"{args.pass_uri}/{clip}/{f}", clip_dir / f)
    model = download(s3, args.model_uri, work / "model.onnx")
    runner = ClipRunner(model, CALIB, load_corridor(ROOT / "data" / "corridor"))
    obs, odo, st = runner.perceive(clip_dir)
    out = work / "out"
    save_perception(out, obs, odo, st)
    upload_tree(s3, out, f"{args.run_uri}/{pass_name}/{clip}")
    print(json.dumps(st), flush=True)
    emf(
        {
            "KmPerceived": st["km"],
            "FramesDecoded": st["frames"],
            "FramesKept": st["kept"],
            "Observations": st["observations"],
            "PerceiveSeconds": st["seconds"],
            **{f"StageSeconds_{k}": v for k, v in st["stage_seconds"].items()},
        },
        {"Stage": "perceive"},
        {"PerceiveSeconds": "Seconds"},
    )


def cmd_assemble(args, s3, work: Path) -> None:
    pass_name = split(args.pass_uri)[1].split("/")[-1]
    pass_dir, run_pass = work / "in" / pass_name, work / "run" / pass_name
    model = download(s3, args.model_uri, work / "model.onnx")
    for clip in list_clips(s3, args.pass_uri):
        for f in CLIP_FILES:
            download(s3, f"{args.pass_uri}/{clip}/{f}", pass_dir / clip / f)
        try:
            download(s3, f"{args.run_uri}/{pass_name}/{clip}/perception.json", run_pass / clip / "perception.json")
        except Exception as e:  # noqa: BLE001 - a failed child: assemble the rest, report it
            print(f"missing perception for {clip}: {e}", flush=True)
    corridor = load_corridor(ROOT / "data" / "corridor")
    runner = ClipRunner(model, CALIB, corridor)
    stats = assemble_pass(corridor, pass_dir, run_pass, runner)
    upload_tree(s3, run_pass, f"{args.run_uri}/{pass_name}")
    summary = {
        "pass": pass_name,
        "clips": len(stats),
        "km": round(sum(s["km"] for s in stats), 3),
        "defects": sum(s["defects"] for s in stats),
        "seconds_perceive": sum(s["seconds"] for s in stats),
    }
    if args.load_register:
        reg = Register()
        loaded = [
            reg.load_clip(run_pass / c.name, json.loads((c / "meta.json").read_text()), args.model_version, "cam01-v1")
            for c in sorted(pass_dir.glob("clip_*"))
            if (run_pass / c.name / "defects.json").exists()
        ]
        summary["register"] = {
            k: sum(x[k] for x in loaded) for k in ("new_observations", "new_defects", "linked_to_existing")
        }
        metas = [json.loads((c / "meta.json").read_text()) for c in sorted(pass_dir.glob("clip_*"))]
        if metas:
            summary["register"]["not_seen_again"] = reg.close_pass(
                metas[0]["pass_id"], [tuple(m["chainage_m"]) for m in metas]
            )
        if args.publish:
            summary["viewer"] = publish([run_pass], f"{pass_name} ({args.source})", register=reg)
    b, k = split(args.run_uri)
    s3.put_object(Bucket=b, Key=f"{k}/{pass_name}/summary.json", Body=json.dumps(summary, indent=1).encode())
    print(json.dumps(summary), flush=True)
    emf(
        {
            "KmProcessed": summary["km"],
            "DefectsFound": summary["defects"],
            "NewDefects": summary.get("register", {}).get("new_defects", 0),
            "LinkedDefects": summary.get("register", {}).get("linked_to_existing", 0),
        },
        {"Stage": "assemble"},
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("perceive", "assemble"):
        p = sub.add_parser(name)
        p.add_argument("--pass-uri", required=True, help="s3://<raw>/<run>/<pass>")
        p.add_argument("--run-uri", required=True, help="s3://<artifacts>/runs/<run>")
        p.add_argument("--model-uri", required=True, help="s3://<artifacts>/models/<version>/model.onnx")
        p.add_argument("--model-version", default="seg-v1")
        p.add_argument("--index", type=int, default=None)
        p.add_argument("--load-register", action="store_true")
        p.add_argument("--publish", action="store_true")
        p.add_argument("--source", default="synthetic survey")
    args = ap.parse_args()
    s3 = boto3.client("s3", region_name=REGION)
    with tempfile.TemporaryDirectory() as tmp:
        (cmd_perceive if args.cmd == "perceive" else cmd_assemble)(args, s3, Path(tmp))


if __name__ == "__main__":
    main()
