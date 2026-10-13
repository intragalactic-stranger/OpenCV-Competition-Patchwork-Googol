"""Batch wrapper for training/prepare.py: S3 in -> prepare -> S3 out (keeps big data off the dev box).

python -m training.prepare_job --synth s3://.../synth/seed07 --merge s3://.../train/pmix_only --out s3://.../train/v1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from training import prepare


def sync(src: str, dst: str) -> None:
    subprocess.run(["aws", "s3", "sync", src, dst, "--only-show-errors"], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", nargs="+", required=True)
    ap.add_argument("--merge", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", type=Path, default=Path("/work"))
    args = ap.parse_args()
    synth_dirs, merge_dirs = [], []
    for i, s in enumerate(args.synth):
        d = args.work / f"synth{i}" / s.rstrip("/").split("/")[-1]
        sync(s, str(d))
        synth_dirs.append(str(d))
    for i, s in enumerate(args.merge):
        d = args.work / f"merge{i}"
        sync(s, str(d))
        merge_dirs.append(str(d))
    out = args.work / "out"
    sys.argv = ["prepare", "--pmix", "/nonexistent", "--out", str(out), "--synth", *synth_dirs]
    if merge_dirs:
        sys.argv += ["--merge", *merge_dirs]
    prepare.main()
    sync(str(out), args.out)


if __name__ == "__main__":
    main()
