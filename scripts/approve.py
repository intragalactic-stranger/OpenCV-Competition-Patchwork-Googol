"""The engineer's side of the approval gate (the web console replaces this in the second half).

  uv run python scripts/approve.py list
  uv run python scripts/approve.py show PACKAGE_ID
  uv run python scripts/approve.py approve PACKAGE_ID --by "AE Ward D" [--note "..."]
  uv run python scripts/approve.py reject  PACKAGE_ID --by "AE Ward D" --note "re-inspect first"

Approving resumes the Step Functions execution, which files a MOCK ticket (nothing is sent to a real
authority). Every decision is stored in `approval`; a rejection is an override of the agent's plan.
"""

from __future__ import annotations

import argparse
import json

import boto3

from patchwork.register.dataapi import Register
from patchwork.schema.models import new_id

REGION = "ap-south-1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "show", "approve", "reject"])
    ap.add_argument("package_id", nargs="?")
    ap.add_argument("--by", default="ward-engineer")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    reg = Register()
    if args.cmd == "list":
        for r in reg.sql(
            "SELECT wp.package_id, wp.priority, wp.total_area_m2, wp.state, wp.pdf_key, (ar.package_id IS NOT NULL) "
            "AS waiting FROM work_package wp LEFT JOIN approval_request ar USING (package_id) "
            "WHERE wp.state IN ('awaiting_approval', 'filed', 'rejected') ORDER BY wp.priority, wp.exposure_score DESC"
        ):
            print(r)
        return
    if not args.package_id:
        raise SystemExit("package_id required")
    if args.cmd == "show":
        p = reg.sql("SELECT * FROM work_package WHERE package_id = :p", {"p": args.package_id})
        print(json.dumps(p, indent=1, default=str))
        return
    tok = reg.sql("SELECT task_token FROM approval_request WHERE package_id = :p", {"p": args.package_id})
    if not tok:
        raise SystemExit("no pending approval for this package (workflow not started, or already decided)")
    sfn = boto3.client("stepfunctions", region_name=REGION)
    decision = {"decision": args.cmd, "decided_by": args.by, "note": args.note}
    if args.cmd == "approve":
        sfn.send_task_success(taskToken=tok[0]["task_token"], output=json.dumps(decision))
    else:
        sfn.send_task_failure(taskToken=tok[0]["task_token"], error="Rejected", cause=json.dumps(decision))
    reg.sql(
        "INSERT INTO approval (approval_id, package_id, decision, decided_by, note, is_override) "
        "VALUES (:a, :p, :d, :by, :n, :o)",
        {"a": new_id(), "p": args.package_id, "d": args.cmd, "by": args.by, "n": args.note, "o": args.cmd == "reject"},
    )
    reg.sql("DELETE FROM approval_request WHERE package_id = :p", {"p": args.package_id})
    print(f"{'approved' if args.cmd == 'approve' else 'rejected'} {args.package_id}")


if __name__ == "__main__":
    main()
