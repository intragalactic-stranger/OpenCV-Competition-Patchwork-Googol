"""Fill the metrics table in docs/midpoint/04-RESULTS-AND-OUTPUTS.md from eval/results/*.json.

Only numbers that exist in result files are written; everything else stays [[TBD]].
Usage: uv run python -m eval.report
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval" / "results"
DOC = ROOT / "docs" / "midpoint" / "04-RESULTS-AND-OUTPUTS.md"


def _load(name: str) -> dict | None:
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def _row(metric: str, target: str, value: str | None, ok: bool | None, note: str = "") -> str:
    status = "⏭" if value is None else ("✅" if ok else "❌") if ok is not None else "ℹ️"
    v = "[[TBD]]" if value is None else value
    return f"| {metric} | {target} | {v}{(' · ' + note) if note else ''} | {status} |"


def build_table() -> str:
    smoke = _load("smoke/opencv5_smoke.json")
    area = _load("area_oracle.json")
    rows = ["| Metric | Target | Result | Status |", "|---|---|---|---|"]
    e2e = _load("end_to_end.json")
    if e2e:
        ps = e2e["passes"]
        vis = sum(p["truth_visible"] for p in ps)
        matched = sum(p["matched"] for p in ps)
        km = sum(p["km"] for p in ps)
        fps = sum(p["false_positives"] for p in ps)
        ckm = sum(p["control_km"] for p in ps)
        cfp = sum(p["fp_control"] for p in ps)
        meas = [m for p in ps for m in p["matches"] if m["meas_m2"] is not None]
        ape = [abs(m["meas_m2"] - m["true_m2"]) / m["true_m2"] * 100 for m in meas]
        recall = matched / max(vis, 1)
        rows.append(
            _row(
                "Detection recall (held-out world, D1)",
                "≥ 0.85",
                f"{recall:.2f}",
                recall >= 0.85,
                f"{matched}/{vis} visible defects over {km:.1f} km; {fps / max(km, 1e-6):.2f} FP/km overall",
            )
        )
        if ckm > 0:
            rows.append(
                _row(
                    "False positives per km, Coastal Road control section (D2)",
                    "≤ 0.5",
                    f"{cfp / ckm:.2f}",
                    cfp / ckm <= 0.5,
                    f"{cfp} FPs over {ckm:.1f} km",
                )
            )
        else:
            rows.append(_row("False positives per km, control section (D2)", "≤ 0.5", None, None))
        if ape:
            mape = sum(ape) / len(ape)
            rows.append(
                _row(
                    "Damaged-area MAPE, end to end (model masks)",
                    "≤ 20%",
                    f"{mape:.1f}%",
                    mape <= 20,
                    f"n={len(ape)} measured defects; see assets/area_scatter.png",
                )
            )
        else:
            rows.append(_row("Damaged-area MAPE, end to end (D1)", "≤ 20%", None, None))
    else:
        rows.append(_row("Detection recall @ ≤ 1 FP/km (D1)", "≥ 0.85", None, None))
        rows.append(_row("False positives per km, control section (D2)", "≤ 0.5", None, None))
        rows.append(_row("Damaged-area MAPE, end to end (D1)", "≤ 20%", None, None))
    if area:
        s = area["summary"]
        est, true_, nom = s.get("estimated_pose"), s.get("true_pose"), s.get("nominal_pose")
        note = (
            f"n={est['n']} defects; median {est['median_ape_pct']}%, p90 {est['p90_ape_pct']}%; "
            f"true-pose {true_['mape_pct']}%, nominal-pitch {nom['mape_pct']}%"
        )
        rows.append(
            _row(
                "Damaged-area MAPE, oracle masks (geometry only, estimated pitch)",
                "≤ 5%",
                f"{est['mape_pct']}%",
                est["mape_pct"] <= 5,
                note,
            )
        )
    else:
        rows.append(_row("Damaged-area MAPE, oracle masks (geometry only)", "≤ 5%", None, None))
    loc = _load("localisation.json")
    if loc:
        lsum = loc["summary"]
        tunnel = f"; tunnel (no GNSS) median {lsum['tunnel_median_m']} m" if lsum.get("tunnel_median_m") else ""
        rows.append(
            _row(
                "Median localisation error",
                "≤ 8 m",
                f"{lsum['median_m']} m",
                lsum["median_m"] <= 8,
                f"p90 {lsum['p90_m']} m; raw GNSS median {lsum['gnss_only_median_m']} m{tunnel}; "
                f"{lsum['frames']} frames",
            )
        )
    else:
        rows.append(_row("Median localisation error", "≤ 8 m", None, None))
    seg = _load("segmentation.json")
    real = seg.get("iou_test_real") if seg else None
    synth = seg.get("iou_val_synth") if seg else None
    note = f"{seg['arch']} in OpenCV {seg['engine']}; see 07-MODEL-CARD" if seg else ""
    rows.append(
        _row(
            "Segmentation IoU (damage), real photos (test split)",
            "reported (aim ≥ 0.55)",
            None if real is None else f"{real:.3f}",
            None if real is None else real >= 0.55,
            note,
        )
    )
    rows.append(
        _row(
            "Segmentation IoU (damage), synthetic held-out stretch",
            "reported (aim ≥ 0.75)",
            None if synth is None else f"{synth:.3f}",
            None if synth is None else synth >= 0.75,
            note,
        )
    )
    par = (seg or {}).get("parity", {})
    if par.get("ENGINE_NEW", {}).get("loaded"):
        rows.append(
            _row(
                "ONNX parity: OpenCV 5 ENGINE_NEW vs onnxruntime (trained SegFormer-B0)",
                "≤ 1e-3",
                f"{par['ENGINE_NEW']['max_abs_diff']:.1e}",
                par["ENGINE_NEW"]["max_abs_diff"] <= 1e-3,
                f"{par['images']} images; {100 * par['ENGINE_NEW']['argmax_agreement']:.3f}% same pixel decisions; "
                + (
                    "ENGINE_CLASSIC cannot load it"
                    if not par.get("ENGINE_CLASSIC", {}).get("loaded")
                    else "CLASSIC loads"
                ),
            )
        )
    elif smoke and smoke.get("dnn", {}).get("runs"):
        worst = max(r["ENGINE_NEW"].get("max_abs_diff", 1) for r in smoke["dnn"]["runs"])
        classic = all(not r["ENGINE_CLASSIC"].get("loaded") for r in smoke["dnn"]["runs"])
        rows.append(
            _row(
                "ONNX parity: OpenCV 5 ENGINE_NEW vs onnxruntime (SegFormer-like smoke graph)",
                "≤ 1e-3",
                f"{worst:.1e}",
                worst <= 1e-3,
                "ENGINE_CLASSIC cannot load it" if classic else "ENGINE_CLASSIC also loads it",
            )
        )
    else:
        rows.append(_row("ONNX parity: OpenCV 5 ENGINE_NEW vs onnxruntime", "≤ 1e-3", None, None))
    triage = _load("triage.json")
    if triage:
        t = triage["summary"]
        rows.append(
            _row(
                "Frame triage: kept frames per km (recall loss)",
                "≤ 620/km, ≤ 2% loss",
                f"{t['kept_per_km']:.0f}/km, {t['recall_loss_pct']}% loss",
                t["kept_per_km"] <= 620 and t["recall_loss_pct"] <= 2,
                f"{t['keep_rate_pct']}% of 15 fps frames; {t['covered_2plus_pct']}% of defects in ≥ 2 kept frames; "
                f"odometry {t['odometry_err_pct']:+}% over {t['true_distance_km']} km",
            )
        )
    else:
        rows.append(_row("Frame triage: kept frames per km (recall loss)", "≤ 620/km, ≤ 2% loss", None, None))
    if e2e and e2e["passes"]:
        ps = e2e["passes"]
        spk = sum(p["seconds_per_km"] * p["km"] for p in ps) / max(sum(p["km"] for p in ps), 1e-6)
        rows.append(
            _row(
                "Processing time per km (Batch, Graviton, 4 vCPU per clip)",
                "reported",
                f"{spk / 60:.1f} vCPU-container-min/km",
                None,
                "clips run in parallel: wall-clock per pass ≈ time of the slowest clip",
            )
        )
    else:
        rows.append(_row("Processing time per km (Batch, Graviton)", "reported", None, None))
    cost = _load("cost_per_km.json")
    rows.append(
        _row(
            "Cost per km processed (perception compute, Graviton Spot)",
            "< $0.02",
            f"${cost['usd_per_km']:.4f}" if cost else None,
            cost["usd_per_km"] < 0.02 if cost else None,
            f"{cost['seconds_per_km']:.0f} s × {cost['vcpu']} vCPU per km at ${cost['spot_usd_per_vcpu_h']}/vCPU-h; "
            f"upper bound incl. data rendering + training ${cost['upper_bound_usd_per_km']}/km; see 02-COST-REPORT"
            if cost
            else "",
        )
    )
    reid = _load("reid.json")
    if reid:
        rows.append(
            _row(
                "Cross-pass re-ID F1, basic matcher (preview)",
                "≥ 0.90 (final, second half)",
                f"{reid['link_f1']:.2f}",
                None,
                f"passes {reid['passes'][0]}→{reid['passes'][1]}: precision {reid['link_precision']}, recall "
                f"{reid['link_recall']}; repaired defects recognised as gone: {reid['repaired_recall']:.0%} "
                f"of {reid['repaired_in_truth_and_detected_in_pass1']}",
            )
        )
    else:
        rows.append(_row("Cross-pass re-ID F1, basic matcher (stretch)", "≥ 0.90 (final)", None, None))
    ab = _load("ablation_ab.json")
    if ab:
        A, B = ab["A"], ab["B"]
        rows.append(
            _row(
                "Run A/B: plan changes with measured area (agent on Amazon Nova)",
                "must change",
                "changed" if ab["plan_changed"] else "NOT changed",
                ab["plan_changed"],
                f"{ab['area_A']:.2f} → {ab['area_B']:.2f} m²: priority {A['priority']} → {B['priority']}, "
                f"hot-mix {A['mass_t']} → {B['mass_t']} t; register source: {ab.get('source', '?').split(' (')[0]}; "
                "see assets/ablation_ab.md",
            )
        )
    else:
        rows.append(_row("Run A/B: plan changes with measured area (stretch)", "must change", None, None))
    rows.append("")
    rows.append(f"_Generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC by `uv run python -m eval.report`._")
    return "\n".join(rows)


def main() -> None:
    text = DOC.read_text()
    pat = re.compile(r"(<!-- METRICS:BEGIN -->\n).*?(\n<!-- METRICS:END -->)", re.S)
    if not pat.search(text):
        raise SystemExit("METRICS markers missing")
    DOC.write_text(pat.sub(lambda m: m.group(1) + build_table() + m.group(2), text))
    print(f"updated {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
