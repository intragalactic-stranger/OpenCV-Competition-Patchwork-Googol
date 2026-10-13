"""Run A / run B ablation: does the measured area change the agent's plan? (agent design §6)

Same defect, same prompt, same model, temperature 0. The only difference: in run B the defect's latest
observation is swapped (inside one recorded DB update) to a much larger measured area. The swap is undone
afterwards. If the plan does not change, the agent is not using the vision, and this script fails.

  uv run python -m eval.ablation_ab [--defect-id ID] [--area-b 3.1]
Writes docs/midpoint/assets/ablation_ab.md and eval/results/ablation_ab.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchwork.agent.run import run
from patchwork.agent.tools import Tools
from patchwork.register.dataapi import Register
from patchwork.schema.models import DefectType, Material, severity_v1

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "docs" / "midpoint" / "assets" / "ablation_ab.md"


def pick_defect(reg: Register) -> dict:
    rows = reg.sql(
        "SELECT d.defect_id, d.road_name, d.chainage_m, d.latest_area_m2, d.latest_severity, d.latest_obs_id "
        "FROM defect d WHERE d.latest_area_m2 BETWEEN 0.15 AND 0.45 AND d.latest_severity <> 'high' "
        "ORDER BY d.chainage_m LIMIT 1"
    )
    if not rows:
        raise SystemExit("no suitable small defect in the register")
    return rows[0]


def set_area(reg: Register, d: dict, area: float) -> None:
    sev, conf = severity_v1(area, DefectType.pothole, None)
    mat = Material.for_area(area).model_dump()
    reg.sql(
        "UPDATE observation SET area_m2 = :a, severity = CAST(:s AS severity), severity_confidence = :c, "
        "material = CAST(:m AS jsonb) WHERE obs_id = :o",
        {"a": area, "s": sev.value, "c": conf, "m": json.dumps(mat), "o": d["latest_obs_id"]},
    )
    reg.sql(
        "UPDATE defect SET latest_area_m2 = :a, latest_severity = CAST(:s AS severity) WHERE defect_id = :d",
        {"a": area, "s": sev.value, "d": d["defect_id"]},
    )


def summarise(out: dict, reg: Register, defect_id: str) -> dict:
    calls = [s for s in out["trace"] if s["type"] == "tool_call"]
    pk = reg.sql(
        "SELECT package_id, priority, exposure_score, total_area_m2, material, state FROM work_package "
        "WHERE agent_run_id = :r AND :d = ANY(defect_ids) ORDER BY created_at DESC",
        {"r": out["run_id"], "d": defect_id},
    )
    p = pk[0] if pk else {}
    mat = json.loads(p["material"]) if isinstance(p.get("material"), str) else p.get("material") or {}
    return {
        "run_id": out["run_id"],
        "tool_sequence": [c["tool"] for c in calls],
        "package_id": p.get("package_id"),
        "priority": p.get("priority"),
        "exposure_score": p.get("exposure_score"),
        "area_m2": p.get("total_area_m2"),
        "mass_t": mat.get("mass_t"),
        "state": p.get("state"),
        "final": out["final"],
        "tokens": out["usage"].get("totalTokens"),
        "seconds": out["seconds"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--defect-id", default=None)
    ap.add_argument("--area-b", type=float, default=3.1)
    args = ap.parse_args()
    reg = Register()
    d = (
        reg.sql(
            "SELECT defect_id, road_name, chainage_m, latest_area_m2, latest_severity, latest_obs_id FROM defect "
            "WHERE defect_id = :d",
            {"d": args.defect_id},
        )[0]
        if args.defect_id
        else pick_defect(reg)
    )
    prompt = (
        f"Plan the repair for defect {d['defect_id']} on {d['road_name']}: query it, package it, estimate "
        "materials, draft the work order and request approval. Explain the priority."
    )
    a_area = float(d["latest_area_m2"])
    src = reg.sql("SELECT model_version FROM observation WHERE obs_id = :o", {"o": d["latest_obs_id"]})[0]
    source = (
        "ground-truth fixture (eval/agent_fixture.py), used until the pipeline has populated the register"
        if src["model_version"] == "ground-truth"
        else f"pipeline output (model {src['model_version']})"
    )
    res = {}
    try:
        res["A"] = summarise(
            run(prompt, run_id=f"ablation-A-{d['defect_id'][-6:]}", tools=Tools(reg)), reg, d["defect_id"]
        )
        set_area(reg, d, args.area_b)
        res["B"] = summarise(
            run(prompt, run_id=f"ablation-B-{d['defect_id'][-6:]}", tools=Tools(reg)), reg, d["defect_id"]
        )
    finally:
        set_area(reg, d, a_area)  # undo the fixture swap whatever happens
    changed = (res["A"]["priority"], res["A"]["mass_t"]) != (res["B"]["priority"], res["B"]["mass_t"])
    result = {
        "defect": {k: d[k] for k in ("defect_id", "road_name", "chainage_m")},
        "source": source,
        "area_A": a_area,
        "area_B": args.area_b,
        "plan_changed": changed,
        **res,
    }
    (ROOT / "eval" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "eval" / "results" / "ablation_ab.json").write_text(json.dumps(result, indent=1, default=str))
    A, B = res["A"], res["B"]
    md = [
        "# Run A vs run B: does the measured area change the plan?",
        "",
        f"Same defect (`{d['defect_id']}`, {d['road_name']}, chainage {float(d['chainage_m']):.0f} m), same prompt, "
        "same model (Amazon Nova Pro, temperature 0). **Only the measured area differs**: in run B the observation "
        f"was swapped from **{a_area:.2f} m²** to **{args.area_b:.2f} m²** for the duration of the run "
        "(then restored).",
        "",
        f"Register row source: **{source}**.",
        "",
        f"**Result: the plan {'CHANGED ✅' if changed else 'DID NOT CHANGE ❌ (test fails)'}**",
        "",
        "| | Run A (measured) | Run B (swapped) |",
        "|---|---|---|",
        f"| Measured area | {a_area:.2f} m² | {args.area_b:.2f} m² |",
        f"| Priority (1 = urgent) | {A['priority']} | {B['priority']} |",
        f"| Exposure score | {A['exposure_score']} | {B['exposure_score']} |",
        f"| Hot-mix needed | {A['mass_t']} t | {B['mass_t']} t |",
        f"| Package state | {A['state']} | {B['state']} |",
        f"| Tool calls | {' → '.join(A['tool_sequence'])} | {' → '.join(B['tool_sequence'])} |",
        f"| Tokens · seconds | {A['tokens']} · {A['seconds']} | {B['tokens']} · {B['seconds']} |",
        "",
        "## Run A: agent's final answer",
        "",
        "> " + A["final"].strip().replace("\n", "\n> "),
        "",
        "## Run B: agent's final answer",
        "",
        "> " + B["final"].strip().replace("\n", "\n> "),
        "",
        f"_Full traces: `eval/results/agent/{A['run_id']}.json`, `eval/results/agent/{B['run_id']}.json`. "
        "Priority and quantities are computed by tools from the database, so the change is caused by the "
        "measurement, not by model randomness._",
    ]
    OUT_MD.write_text("\n".join(md) + "\n")
    print(
        json.dumps(
            {
                "plan_changed": changed,
                "A": {k: A[k] for k in ("priority", "mass_t")},
                "B": {k: B[k] for k in ("priority", "mass_t")},
            }
        )
    )
    if not changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
