"""Publish the map viewer from the dev box (the Batch assemble job does the same after every pass).

uv run python scripts/aws/deploy_viewer.py [--overlays runs/e2e] [--source "held-out world, pass 1"]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from patchwork.pipeline.publish import publish

ROOT = Path(__file__).resolve().parents[2]


def tf_output(name: str, raw: bool = True) -> str:
    return subprocess.run(
        ["terraform", "output", "-raw" if raw else "-json", name],
        cwd=ROOT / "infra" / "terraform" / "envs" / "dev",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlays", type=Path, nargs="*", default=[])
    ap.add_argument("--source", default="synthetic survey, held-out world (seed 11)")
    args = ap.parse_args()
    subprocess.run([str(ROOT / "scripts" / "aws" / "location_key.sh")], capture_output=True, check=True)
    try:  # null (or absent) unless the console stack is deployed with enable_console = true
        console = json.loads(tf_output("console", raw=False))
    except subprocess.CalledProcessError:
        console = None
    meta = publish(
        args.overlays,
        args.source,
        bucket=tf_output("viewer_bucket"),
        distribution=tf_output("viewer_distribution_id"),
        console=console,
    )
    print(f"published {meta['defects']} defects ({meta['overlays']} overlays) -> {tf_output('viewer_url')}")


if __name__ == "__main__":
    main()
