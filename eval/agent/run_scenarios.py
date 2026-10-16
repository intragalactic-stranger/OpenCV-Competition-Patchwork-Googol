"""Run (or re-score) the 40 agent scenarios in eval/agent/scenarios.yaml.

Live mode runs Amazon Nova with the real tools on the real register, one scenario per database transaction,
rolled back at the end: nothing a scenario creates (packages, re-inspections) survives. No approval workflow
is started (no Step Functions ARN is passed), so no approval request is left waiting.
Re-score mode (`--rescore`, used in CI) checks the assertions again on the saved traces, offline.

  uv run --group agent python -m eval.agent.run_scenarios [--only A01,C03]
  uv run python -m eval.agent.run_scenarios --rescore
Writes eval/results/agent/scenarios/<id>.json (traces) and eval/results/agent_scenarios.json (summary).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = Path(__file__).parent / "scenarios.yaml"
TRACES = ROOT / "eval" / "results" / "agent" / "scenarios"
SUMMARY = ROOT / "eval" / "results" / "agent_scenarios.json"
WRITES = {
    "cluster_into_packages",
    "estimate_materials",
    "draft_work_order",
    "request_human_approval",
    "schedule_reinspection",
    "verify_repair",
}
FAKE_DEFECT = "01ZZZZZZZZZZZZZZZZZZZZZZZZ"
FAKE_PACKAGE = "01ZZZZZZZZZZZZZZZZZZZZZZZY"
NUM = re.compile(r"\d+(?:\.\d+)?")


def placeholders(reg) -> dict[str, str]:
    """Concrete IDs for the {placeholders}, read from the register (read-only)."""

    def one(q: str) -> dict:
        r = reg.sql(q)
        return r[0] if r else {}

    big = one(
        "SELECT defect_id, latest_area_m2 FROM defect WHERE latest_area_m2 IS NOT NULL "
        "ORDER BY latest_area_m2 DESC LIMIT 1"
    )
    small = one("SELECT defect_id FROM defect WHERE latest_area_m2 IS NOT NULL ORDER BY latest_area_m2 LIMIT 1")
    unmeasured = one(
        "SELECT d.defect_id FROM defect d JOIN observation o ON o.obs_id = d.latest_obs_id "
        "WHERE o.measurement_status = 'detected_not_measured' ORDER BY d.defect_id LIMIT 1"
    )
    active = one(
        "SELECT w.package_id, w.defect_ids[1] AS defect_id, d.road_name FROM work_package w "
        "JOIN defect d ON d.defect_id = w.defect_ids[1] WHERE w.state = 'awaiting_approval' "
        "ORDER BY w.created_at LIMIT 1"
    )
    filed = one(
        "SELECT package_id FROM work_package WHERE state IN ('filed', 'verified', 'escalated') "
        "ORDER BY created_at LIMIT 1"
    )
    return {
        "largest_defect": big.get("defect_id", ""),
        "largest_area": f"{big['latest_area_m2']:.2f}" if big else "",
        "smallest_defect": small.get("defect_id", ""),
        "unmeasured_defect": unmeasured.get("defect_id", ""),
        "packaged_defect": active.get("defect_id", ""),
        "active_package": active.get("package_id", ""),
        "active_road": active.get("road_name", ""),
        "filed_package": filed.get("package_id", ""),
        "fake_defect": FAKE_DEFECT,
        "fake_package": FAKE_PACKAGE,
    }


def fill(x, ph: dict[str, str]):
    if isinstance(x, str):
        return re.sub(r"\{(\w+)\}", lambda m: ph.get(m.group(1), m.group(0)), x)
    if isinstance(x, list):
        return [fill(v, ph) for v in x]
    return x


def _json(x):
    if isinstance(x, (list, dict)):
        return x
    try:
        return json.loads(x)
    except (TypeError, ValueError):
        return None


def score(sc: dict, out: dict) -> dict:
    """Check one scenario's assertions against its trace. Returns {passed, failures}."""
    calls = [s["tool"] for s in out["trace"] if s["type"] == "tool_call"]
    results = " ".join(str(s.get("result")) for s in out["trace"] if s["type"] == "tool_result")
    final = out.get("final", "")
    fails = []
    for t in sc.get("must_call", []):
        if t not in calls:
            fails.append(f"did not call {t}")
    for t in sc.get("must_not_call", []):
        if t in calls:
            fails.append(f"called {t}")
    seq, i = sc.get("sequence", []), 0
    for c in calls:
        if i < len(seq) and c == seq[i]:
            i += 1
    if i < len(seq):
        fails.append(f"sequence broken at {seq[i]}")
    if (e := sc.get("expect_error")) and e not in results:
        fails.append(f"no {e} error")
    for pat in sc.get("final_absent", []):
        if re.search(pat, final, re.I):
            fails.append(f"answer matches forbidden /{pat}/")
    for pat in sc.get("final_present", []):
        try:  # a number: accept any value in the answer within 1 %
            v = float(pat)
            if not any(abs(float(n) - v) <= 0.01 * max(v, 0.01) for n in NUM.findall(final)):
                fails.append(f"answer lacks {pat}")
        except ValueError:
            if not re.search(pat, final, re.I):
                fails.append(f"answer lacks /{pat}/")
    if (mx := sc.get("max_approvals")) is not None and calls.count("request_human_approval") > mx:
        fails.append(f"{calls.count('request_human_approval')} approvals requested > {mx}")
    if sc.get("read_only") and (w := sorted(set(calls) & WRITES)):
        fails.append(f"read-only question, but called {w}")
    if sc.get("plan_complete"):
        ids = {s["id"]: s["tool"] for s in out["trace"] if s["type"] == "tool_call"}
        created, low = set(), set()
        for s in out["trace"]:
            if s["type"] == "tool_result" and ids.get(s["id"]) == "cluster_into_packages" and s.get("result"):
                for pkg in _json(s["result"]) if isinstance(_json(s["result"]), list) else []:
                    created.add(pkg["package_id"])
                    if pkg.get("below_confidence_floor"):
                        low.add(pkg["package_id"])
        asked = {
            str(s["input"].get("package_id"))
            for s in out["trace"]
            if s["type"] == "tool_call" and s["tool"] == "request_human_approval"
        }
        reinspect = "schedule_reinspection" in calls
        for pid in created:
            if pid not in asked and not (pid in low and reinspect):
                fails.append(f"package {pid} neither sent for approval nor (low confidence) re-inspected")
        if not created:
            fails.append("no package created")
    if (m := sc.get("max_calls")) is not None and len(calls) > m:
        fails.append(f"{len(calls)} tool calls > {m}")
    if out.get("error"):
        fails.append(f"run error: {out['error'][:120]}")
    chk = out.get("answer_check", {})
    ungrounded = [i for i in chk.get("ungrounded_ids", []) if i not in sc["prompt"]]  # echoing the user's ID is fine
    if ungrounded:
        fails.append(f"ungrounded IDs in answer: {ungrounded}")
    return {"passed": not fails, "failures": fails, "tool_calls": calls, "ungrounded_ids": ungrounded}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma list of scenario IDs")
    ap.add_argument("--rescore", action="store_true", help="re-check saved traces offline (CI)")
    args = ap.parse_args()
    spec = yaml.safe_load(SCENARIOS.read_text())["scenarios"]
    if args.only:
        keep = set(args.only.split(","))
        spec = [s for s in spec if s["id"] in keep]

    rows = []
    if args.rescore:
        for sc in spec:
            f = TRACES / f"{sc['id']}.json"
            if f.exists():
                out = json.loads(f.read_text())
                rows.append(
                    {
                        "id": sc["id"],
                        "category": sc["category"],
                        **score(out["scenario"], out),
                        "seconds": out["seconds"],
                        "tokens": out["usage"].get("totalTokens", 0),
                    }
                )
    else:
        from patchwork.agent.run import run
        from patchwork.agent.tools import Tools
        from patchwork.register.dataapi import Register

        reg = Register()
        reg.sql("SELECT 1")  # wake an auto-paused cluster before the first transaction
        ph = placeholders(reg)
        print(json.dumps(ph), flush=True)
        for sc in spec:
            if (need := sc.get("requires")) and not ph.get(need):
                rows.append({"id": sc["id"], "category": sc["category"], "passed": None, "failures": ["skipped"]})
                continue
            sc = {k: fill(v, ph) for k, v in sc.items()}
            t0, out = time.time(), None
            for attempt in (1, 2):  # a model-side error (e.g. a malformed tool call) gets one retry, then counts
                reg = Register()
                reg.begin()
                try:
                    out = run(sc["prompt"], run_id=sc["id"], tools=Tools(reg), out_dir=TRACES)
                    break
                except Exception as e:  # noqa: BLE001 - recorded as a scenario failure, the suite continues
                    err = f"{type(e).__name__}: {str(e)[:300]}"
                    print(json.dumps({"id": sc["id"], "attempt": attempt, "error": err}), flush=True)
                finally:
                    reg.rollback()
            if out is None:
                out = {"trace": [], "final": "", "seconds": round(time.time() - t0, 1), "usage": {}, "error": err}
            out["scenario"] = sc
            (TRACES / f"{sc['id']}.json").write_text(json.dumps(out, indent=1, default=str))
            r = {
                "id": sc["id"],
                "category": sc["category"],
                **score(sc, out),
                "seconds": round(time.time() - t0, 1),
                "tokens": out["usage"].get("totalTokens", 0),
            }
            rows.append(r)
            print(json.dumps({k: r[k] for k in ("id", "passed", "failures", "tool_calls", "tokens")}), flush=True)

    ran = [r for r in rows if r["passed"] is not None]
    by_cat = {}
    for r in ran:
        c = by_cat.setdefault(r["category"], [0, 0])
        c[0] += bool(r["passed"])
        c[1] += 1
    summary = {
        "scenarios": len(rows),
        "ran": len(ran),
        "passed": sum(bool(r["passed"]) for r in ran),
        "ungrounded_id_answers": sum(bool(r.get("ungrounded_ids")) for r in ran),
        "by_category": {k: f"{a}/{b}" for k, (a, b) in sorted(by_cat.items())},
        "tokens": sum(r.get("tokens", 0) for r in ran),
        "rows": rows,
    }
    if not args.only:
        SUMMARY.write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
    if summary["ungrounded_id_answers"]:
        raise SystemExit("hard gate: an answer cited an ID that is not in the register")


if __name__ == "__main__":
    main()
