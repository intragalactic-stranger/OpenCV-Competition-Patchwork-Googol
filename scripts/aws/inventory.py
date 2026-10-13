"""List every deployed resource tagged Project=patchwork, grouped by service, into 03-SERVICES-USED.md.

uv run python scripts/aws/inventory.py      (make services-inventory)
"""

from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "midpoint" / "03-SERVICES-USED.md"


def resources(region: str) -> list[str]:
    tag = boto3.client("resourcegroupstaggingapi", region_name=region)
    arns, token = [], ""
    while True:
        r = tag.get_resources(TagFilters=[{"Key": "Project", "Values": ["patchwork"]}], PaginationToken=token)
        arns += [m["ResourceARN"] for m in r["ResourceTagMappingList"]]
        token = r.get("PaginationToken", "")
        if not token:
            return arns


def main() -> None:
    arns = resources("ap-south-1") + resources("us-east-1")  # us-east-1: CloudFront and other global resources
    # durable infrastructure only: skip per-run items (Batch jobs, Spot instances and their volumes, ECS tasks)
    ephemeral = (":job/", ":instance/", ":volume/", ":task/", ":spot-instances-request/", ":network-interface/")
    arns = [a for a in set(arns) if not any(e in a for e in ephemeral)]
    by = collections.defaultdict(list)
    for a in sorted(arns):
        parts = a.split(":")
        svc = parts[2]
        name = ":".join(parts[5:])  # e.g. job-definition/patchwork-perceive:1
        by[svc].append(name.split("/", 1)[-1] if "/" in name else name)
    rows = ["| Service | Count | Resources |", "|---|---|---|"]
    for svc, names in sorted(by.items()):
        shown = ", ".join(f"`{n}`" for n in names[:8]) + (f" … (+{len(names) - 8})" if len(names) > 8 else "")
        rows.append(f"| {svc} | {len(names)} | {shown} |")
    rows += ["", f"_{len(arns)} tagged resources · generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC._"]
    text = DOC.read_text()
    pat = re.compile(r"(<!-- INVENTORY:BEGIN -->\n).*?(\n<!-- INVENTORY:END -->)", re.S)
    DOC.write_text(pat.sub(lambda m: m.group(1) + "\n".join(rows) + m.group(2), text))
    print(f"{len(arns)} resources in {len(by)} services")


if __name__ == "__main__":
    main()
