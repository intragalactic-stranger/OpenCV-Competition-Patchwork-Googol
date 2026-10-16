"""Ask the Ward Engineer's Assistant hosted on Amazon Bedrock AgentCore Runtime (IAM-authenticated).

uv run python scripts/aws/invoke_agent.py "Plan repairs for Hughes Road."
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "How many defects are recorded on Hughes Road?"
    arn = subprocess.run(
        ["terraform", "output", "-raw", "agent_runtime_arn"],
        cwd=ROOT / "infra/terraform/envs/dev",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    r = boto3.client("bedrock-agentcore", region_name="ap-south-1").invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=f"patchwork-{uuid.uuid4().hex}",  # >= 33 characters
        payload=json.dumps({"prompt": prompt}).encode(),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(r["response"].read())
    print(
        json.dumps(
            {k: body.get(k) for k in ("run_id", "runtime", "tool_calls", "answer_check", "usage", "error")}, indent=1
        )
    )
    print(body.get("final", ""))


if __name__ == "__main__":
    main()
