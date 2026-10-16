"""Render the survey corridor map (main_docs/midpoint/assets/corridor_map.png)."""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from patchwork.synth.corridor import load_corridor  # noqa: E402

OSM = ROOT / "data" / "raw" / "osm" / "roads_raw.json"


def main() -> None:
    c = load_corridor(ROOT / "data" / "corridor")
    d = json.loads(OSM.read_text())
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in d["elements"] if e["type"] == "node"}
    fig, ax = plt.subplots(figsize=(7, 9))
    for e in d["elements"]:
        if e["type"] == "way":
            pts = [nodes[i] for i in e["nodes"] if i in nodes]
            ax.plot(*zip(*pts, strict=True), color="#d9d9d9", lw=0.4, zorder=1)
    styles = {
        "control": dict(color="#2a6f97", lw=2.6, label="Coastal Road (control section)"),
        "tunnel": dict(color="#2a6f97", lw=2.6, ls=(0, (2, 1.5)), label="Coastal Road tunnel (no GNSS)"),
        "arterial": dict(color="#d1495b", lw=2.2, label="Feeder arterials (defects expected)"),
    }
    used = set()
    for seg in c.segments:
        kind = "tunnel" if seg.is_tunnel else "control" if seg.is_control else "arterial"
        idx = (c.s >= seg.chainage_start_m) & (c.s <= seg.chainage_end_m)
        st = dict(styles[kind])
        if kind in used:
            st.pop("label")
        used.add(kind)
        ax.plot(c.lon[idx], c.lat[idx], zorder=3, **st)
    ax.plot(c.lon[0], c.lat[0], "o", color="black", ms=6, zorder=4, label="Start / end (Nariman Point)")
    for name, (lo, la) in {
        "Marine Drive": (72.8245, 18.940),
        "Worli Seaface": (72.8195, 19.003),
        "Haji Ali": (72.8150, 18.9815),
        "Prabhadevi": (72.8235, 19.0150),
        "Breach Candy": (72.8080, 18.9700),
    }.items():
        ax.annotate(name, (lo, la), fontsize=8, color="#333")
    ctrl = sum(s.length_m for s in c.segments if s.is_control) / 1000
    ax.set_title(f"Patchwork survey loop: {c.length_m / 1000:.1f} km (control {ctrl:.1f} km)", fontsize=11)
    ax.set_xlim(c.lon.min() - 0.006, c.lon.max() + 0.012)
    ax.set_ylim(c.lat.min() - 0.004, c.lat.max() + 0.004)
    ax.set_aspect(1 / 0.946)  # cos(19 deg)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.legend(loc="lower left", fontsize=8, frameon=True)
    ax.text(
        0.99,
        0.005,
        "Map data © OpenStreetMap contributors (ODbL)",
        transform=ax.transAxes,
        ha="right",
        fontsize=6,
        color="#666",
    )
    out = ROOT / "main_docs" / "midpoint" / "assets" / "corridor_map.png"
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    print(out)


if __name__ == "__main__":
    main()
