"""One-time local setup for a fresh clone: OSM corridor + POIs, and the camera calibration.

  1. data/raw/osm/*.json      downloaded from Overpass if missing (scripts/data/fetch_osm.py)
  2. data/corridor/           the 28.6 km survey loop, road segments and nearby POIs
  3. data/calib/cam01-v1.json ChArUco views rendered through the synthetic camera, then cv2.calibrateCamera

Usage: uv run python scripts/setup_world.py [--force]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from patchwork.camera import CameraModel
from patchwork.perception import calib
from patchwork.synth import charuco
from patchwork.synth.corridor import build_corridor, corridor_pois, save_corridor, save_pois

ROOT = Path(__file__).resolve().parents[1]
OSM = ROOT / "data" / "raw" / "osm"
CORRIDOR = ROOT / "data" / "corridor"
CALIB = ROOT / "data" / "calib" / "cam01-v1.json"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="rebuild even if the outputs exist")
    args = ap.parse_args(argv)

    if not (OSM / "roads_raw.json").exists() or not (OSM / "poi_raw.json").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "data" / "fetch_osm.py"), "all"], check=True)

    if args.force or not (CORRIDOR / "corridor.npz").exists():
        c = build_corridor(json.loads((OSM / "roads_raw.json").read_text()))
        save_corridor(c, CORRIDOR)
        pois = corridor_pois(c, json.loads((OSM / "poi_raw.json").read_text()))
        save_pois(pois, CORRIDOR)
        print(f"corridor: {c.length_m / 1000:.1f} km, {len(c.segments)} segments, {len(pois)} POIs -> {CORRIDOR}")

    if args.force or not CALIB.exists():
        with tempfile.TemporaryDirectory() as tmp:
            views = charuco.render_views(CameraModel(), Path(tmp), seed=7)
            cal = calib.calibrate(views, "cam01-v1")
        CALIB.parent.mkdir(parents=True, exist_ok=True)
        calib.save(cal, CALIB)
        print(f"calibration: RMS {cal.rms_px:.3f} px -> {CALIB}")


if __name__ == "__main__":
    main()
