"""AWS Batch array job: render one synthetic clip and upload it to S3 (decision D-13).

Each array child maps AWS_BATCH_JOB_ARRAY_INDEX -> (pass, clip), rebuilds the deterministic world (~1 s),
renders only its clip, then uploads the pass directory to s3://<bucket>/<prefix>/seedNN/... using the same
layout as a local run, so `aws s3 sync` gives back exactly what `python -m patchwork.synth` would write.

  python -m patchwork.pipeline.synth_job --bucket B --prefix synth --seed 7 --passes 1,2,3 --clip-m 3000
  (locally: AWS_BATCH_JOB_ARRAY_INDEX=4 python -m patchwork.pipeline.synth_job ... --dry-run)
"""

from __future__ import annotations

import argparse
import math
import os
import tempfile
import time
from pathlib import Path

from patchwork.synth import __main__ as synth
from patchwork.synth.corridor import load_corridor

ROOT = Path(__file__).resolve().parents[3]


def n_clips(length_m: float, clip_m: float) -> int:
    return math.ceil(length_m / clip_m)


def task_for(index: int, passes: list[int], clips_per_pass: int) -> tuple[int, int]:
    return passes[index // clips_per_pass], index % clips_per_pass


def upload_tree(local: Path, bucket: str, prefix: str) -> int:
    import boto3
    from boto3.s3.transfer import TransferConfig

    s3 = boto3.client("s3")
    cfg = TransferConfig(max_concurrency=16)
    n = 0
    for p in sorted(local.rglob("*")):
        if p.is_file():
            s3.upload_file(str(p), bucket, f"{prefix}/{p.relative_to(local).as_posix()}", Config=cfg)
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="synth")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--passes", default="1,2,3")
    ap.add_argument("--clip-m", type=float, default=3000.0)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--truth-every", type=int, default=5)
    ap.add_argument("--index", type=int, default=None, help="override AWS_BATCH_JOB_ARRAY_INDEX")
    ap.add_argument("--dry-run", action="store_true", help="print the task and exit")
    args = ap.parse_args()

    passes = [int(p) for p in args.passes.split(",")]
    corridor = load_corridor(ROOT / "data" / "corridor")
    per_pass = n_clips(corridor.length_m, args.clip_m)
    index = args.index if args.index is not None else int(os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX", "0"))
    if index >= per_pass * len(passes):
        raise SystemExit(f"index {index} out of range ({per_pass} clips x {len(passes)} passes)")
    k, ci = task_for(index, passes, per_pass)
    print(f"task {index}: pass {k} clip {ci:02d} of {per_pass} (array size {per_pass * len(passes)})", flush=True)
    if args.dry_run:
        return

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        synth.main(
            [
                f"--seed={args.seed}",
                f"--passes={k}",
                f"--n-passes={max(passes)}",
                f"--clip-m={args.clip_m}",
                f"--fps={args.fps}",
                f"--truth-every={args.truth_every}",
                f"--clips={ci}",
                f"--out={out}",
            ]
        )
        n = upload_tree(out, args.bucket, args.prefix)
    print(f"uploaded {n} files to s3://{args.bucket}/{args.prefix}/ in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
