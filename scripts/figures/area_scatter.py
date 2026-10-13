"""Measured vs true area for every matched defect (end-to-end, model masks) -> docs/midpoint/assets/area_scatter.png

uv run python scripts/figures/area_scatter.py [eval/results/end_to_end.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COLORS = {"pothole": "#d1352b", "edge_break": "#2a6f97", "depression": "#e0a100"}


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "results" / "end_to_end.json"
    passes = json.loads(src.read_text())["passes"]
    m = [x for p in passes for x in p["matches"] if x["meas_m2"] is not None]
    fig, ax = plt.subplots(figsize=(6.2, 6))
    hi = max(max(x["true_m2"] for x in m), max(x["meas_m2"] for x in m)) * 1.1
    ax.plot([0, hi], [0, hi], color="#888", lw=1, label="perfect")
    ax.fill_between([0, hi], [0, 0.8 * hi], [0, 1.2 * hi], color="#2e9e5b", alpha=0.08, label="±20 % (target)")
    for k, c in COLORS.items():
        xs = [x for x in m if x["kind"] == k]
        if xs:
            ax.errorbar(
                [x["true_m2"] for x in xs],
                [x["meas_m2"] for x in xs],
                yerr=[x["unc_m2"] or 0 for x in xs],
                fmt="o",
                ms=4,
                color=c,
                ecolor=c,
                elinewidth=0.6,
                alpha=0.85,
                label=f"{k} (n={len(xs)})",
            )
    ape = np.array([abs(x["meas_m2"] - x["true_m2"]) / x["true_m2"] for x in m]) * 100
    ax.set_xlim(0, hi)
    ax.set_ylim(0, hi)
    ax.set_xlabel("true area (m²), exact synthetic ground truth")
    ax.set_ylabel("measured area (m²), model mask → bird's-eye view")
    ax.set_title(
        f"End-to-end area, held-out world · n={len(m)} · MAPE {ape.mean():.1f}% · median {np.median(ape):.1f}%",
        fontsize=10,
    )
    ax.legend(fontsize=8, loc="upper left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    out = ROOT / "docs" / "midpoint" / "assets" / "area_scatter.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
