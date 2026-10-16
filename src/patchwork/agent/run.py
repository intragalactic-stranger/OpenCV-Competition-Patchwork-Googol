"""Run the Ward Engineer's Assistant (Strands Agents + Amazon Nova on Bedrock) and save its trace.

  uv run python -m patchwork.agent.run "Plan repairs for Marine Drive" [--model apac.amazon.nova-pro-v1:0]
The trace (every tool call with arguments and results, plus the final answer) is written to
eval/results/agent/<run_id>.json, and to S3 when PATCHWORK_ARTIFACTS_BUCKET is set.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.executors import SequentialToolExecutor

from patchwork.agent.tools import ToolError, Tools, tools_from_env
from patchwork.schema.models import new_id

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = "apac.amazon.nova-pro-v1:0"  # first-party model only (decisions D-17, D-27)
SYSTEM = (Path(__file__).parent / "prompts" / "system.md").read_text()


def build_agent(t: Tools, model_id: str = DEFAULT_MODEL) -> Agent:
    def guard(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ToolError as e:
            return {"error": e.code, "detail": e.detail}

    @tool
    def query_defects(
        road_name: str = "",
        min_area_m2: float = 0.0,
        status: str = "",
        limit: int = 50,
        defect_ids: list[str] | None = None,
    ) -> list:
        """List defects in the register, largest first.

        Args:
            road_name: substring of the road name ("" for all roads)
            min_area_m2: only defects at least this large (m²)
            status: new | unchanged | degraded | repaired ("" for any)
            limit: maximum rows (<= 200)
            defect_ids: fetch exactly these defects ([] for no ID filter)
        """
        return guard(t.query_defects, road_name or None, min_area_m2, status or None, limit, defect_ids or None)

    @tool
    def cluster_into_packages(defect_ids: list[str], max_gap_m: float = 30.0) -> list:
        """Group defects into work packages (same road segment, contiguous chainage). Returns each package with
        its deterministic exposure score, priority (1 = most urgent), confidence and nearby schools/hospitals.

        Args:
            defect_ids: defect IDs exactly as returned by query_defects
            max_gap_m: maximum chainage gap inside one package (m)
        """
        return guard(t.cluster_into_packages, defect_ids, max_gap_m)

    @tool
    def estimate_materials(package_id: str, thickness_m: float = 0.05) -> dict:
        """Hot-mix quantity for a package from its measured area and a stated patch thickness (0.02-0.15 m).

        Args:
            package_id: package ID from cluster_into_packages
            thickness_m: assumed patch thickness in metres
        """
        return guard(t.estimate_materials, package_id, thickness_m)

    @tool
    def draft_work_order(package_id: str, rationale: str) -> dict:
        """Write the work order for a package. Numbers are filled from the database; you supply the rationale.

        Args:
            package_id: package ID from cluster_into_packages
            rationale: 2-5 sentences explaining the priority, citing defect IDs
        """
        return guard(t.draft_work_order, package_id, rationale)

    @tool
    def request_human_approval(package_id: str) -> dict:
        """Ask the ward engineer to approve a drafted work order. Nothing is filed without this approval.

        Args:
            package_id: package ID whose work order has been drafted
        """
        return guard(t.request_human_approval, package_id)

    @tool
    def lookup_context(defect_id: str) -> dict:
        """Schools and hospitals within 150 m and bus stops within 50 m of a defect (OpenStreetMap).

        Args:
            defect_id: a defect ID from query_defects
        """
        return guard(t.lookup_context, defect_id)

    @tool
    def check_existing_tickets(defect_ids: list[str]) -> list:
        """Active work packages or filed tickets that already cover any of these defects. Call this before
        clustering so a defect is never ordered twice.

        Args:
            defect_ids: defect IDs from query_defects
        """
        return guard(t.check_existing_tickets, defect_ids)

    @tool
    def schedule_reinspection(defect_ids: list[str], reason: str, package_id: str = "") -> dict:
        """Ask the next survey pass to look again at these defects (low confidence, not measured, or a
        repair to confirm). Only when the user asked you to plan or act, never to answer a question.

        Args:
            defect_ids: defect IDs to look at again
            reason: one sentence: why a second look is needed
            package_id: the related package, if any ("" for none)
        """
        return guard(t.schedule_reinspection, defect_ids, reason, package_id or None)

    @tool
    def verify_repair(package_id: str) -> dict:
        """Check whether a filed package's defects are gone in the latest survey pass. Marks the package
        verified (all gone) or escalated (some remain).

        Args:
            package_id: a package ID
        """
        return guard(t.verify_repair, package_id)

    model = BedrockModel(model_id=model_id, region_name="ap-south-1", temperature=0.0, max_tokens=2048)
    return Agent(
        model=model,
        system_prompt=SYSTEM,
        tools=[
            query_defects,
            lookup_context,
            check_existing_tickets,
            cluster_into_packages,
            estimate_materials,
            draft_work_order,
            request_human_approval,
            schedule_reinspection,
            verify_repair,
        ],
        callback_handler=None,
        tool_executor=SequentialToolExecutor(),  # one tool at a time: deterministic order, one DB transaction
    )


def trace_of(agent: Agent) -> list[dict]:
    steps = []
    for m in agent.messages:
        for c in m.get("content", []):
            if "toolUse" in c:
                steps.append(
                    {
                        "type": "tool_call",
                        "tool": c["toolUse"]["name"],
                        "input": c["toolUse"]["input"],
                        "id": c["toolUse"]["toolUseId"],
                    }
                )
            elif "toolResult" in c:
                body = c["toolResult"].get("content", [])
                text = body[0].get("text") if body and "text" in body[0] else body[0].get("json") if body else None
                steps.append(
                    {
                        "type": "tool_result",
                        "id": c["toolResult"]["toolUseId"],
                        "status": c["toolResult"].get("status"),
                        "result": text,
                    }
                )
            elif "text" in c and m["role"] == "assistant":
                steps.append({"type": "assistant_text", "text": c["text"]})
    return steps


ULID = re.compile(r"\b01[0-9A-HJKMNP-TV-Z]{24}\b")


def check_answer(final: str, trace: list[dict], t: Tools) -> dict:
    """Grounding of the final prose (the database is already guarded; this checks what the model *says*):
    every ID in the answer must exist, and every package created in this run should be mentioned once."""
    cited = ULID.findall(final)
    known = set()
    if cited:
        rows = t.reg.sql(
            "SELECT defect_id AS i FROM defect WHERE defect_id = ANY(string_to_array(:ids, ',')) UNION "
            "SELECT package_id FROM work_package WHERE package_id = ANY(string_to_array(:ids, ',')) UNION "
            "SELECT reinspection_id FROM reinspection WHERE reinspection_id = ANY(string_to_array(:ids, ','))",
            {"ids": ",".join(set(cited))},
        )
        known = {r["i"] for r in rows}
    created = set()
    cluster_calls = {s["id"] for s in trace if s["type"] == "tool_call" and s["tool"] == "cluster_into_packages"}
    for s in trace:
        if s["type"] == "tool_result" and s["id"] in cluster_calls and s.get("result"):
            created |= set(re.findall(r"[\"']package_id[\"']:\s*[\"'](01[0-9A-HJKMNP-TV-Z]{24})", str(s["result"])))
    return {
        "ids_cited": len(set(cited)),
        "ungrounded_ids": sorted(set(cited) - known),
        "packages_created": len(created),
        "packages_not_mentioned": sorted(created - set(cited)),
        "packages_mentioned_more_than_once": sorted(i for i in created if cited.count(i) > 1),
    }


def run(
    prompt: str,
    model_id: str = DEFAULT_MODEL,
    run_id: str | None = None,
    tools: Tools | None = None,
    out_dir: Path | None = None,
) -> dict:
    run_id = run_id or f"agent-{dt.datetime.now(dt.UTC):%Y%m%d-%H%M%S}-{new_id()[-6:]}"
    t = tools or tools_from_env(run_id)
    t.run_id = run_id
    agent = build_agent(t, model_id)
    t0 = time.time()
    result = agent(prompt)
    usage = result.metrics.accumulated_usage if hasattr(result, "metrics") else {}
    final = str(result)
    out = {
        "run_id": run_id,
        "model": model_id,
        "prompt": prompt,
        "seconds": round(time.time() - t0, 1),
        "usage": dict(usage) if usage else {},
        "final": final,
        "trace": trace_of(agent),
    }
    out["answer_check"] = check_answer(final, out["trace"], t)
    d = out_dir or ROOT / "eval" / "results" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run_id}.json").write_text(json.dumps(out, indent=1, default=str))
    bucket = os.environ.get("PATCHWORK_ARTIFACTS_BUCKET")
    if bucket:
        import boto3

        boto3.client("s3", region_name="ap-south-1").put_object(
            Bucket=bucket, Key=f"traces/{run_id}.json", Body=json.dumps(out, default=str).encode()
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    out = run(args.prompt, args.model)
    calls = [s["tool"] for s in out["trace"] if s["type"] == "tool_call"]
    print(json.dumps({"run_id": out["run_id"], "seconds": out["seconds"], "tool_calls": calls, "usage": out["usage"]}))
    print(out["final"])


if __name__ == "__main__":
    main()
