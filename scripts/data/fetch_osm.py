"""Download the OpenStreetMap extracts Patchwork needs (roads + points of interest) via Overpass.

Data © OpenStreetMap contributors, ODbL 1.0. Writes data/raw/osm/{roads_raw,poi_raw}.json + SOURCE.md.
Usage: uv run python scripts/data/fetch_osm.py [roads|poi|all]
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "osm"
BBOX = "18.915,72.795,19.025,72.840"  # south,west,north,east: Nariman Point .. Prabhadevi
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
USER_AGENT = "Patchwork/0.1 (OpenCV AI Competition 2026 research project)"

QUERIES = {
    "roads": f"""[out:json][timeout:180];
way["highway"~"^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|unclassified|residential)$"]({BBOX});
(._;>;);
out body;""",
    "poi": f"""[out:json][timeout:180];
(
  nwr["amenity"~"^(school|college|university|kindergarten|hospital|clinic)$"]({BBOX});
  node["highway"="bus_stop"]({BBOX});
  node["public_transport"="platform"]["bus"="yes"]({BBOX});
);
out center tags;""",
}


def fetch(query: str, attempts: int = 6) -> bytes:
    last = None
    for i in range(attempts):
        url = ENDPOINTS[i % len(ENDPOINTS)]
        req = urllib.request.Request(
            url + "?" + urllib.parse.urlencode({"data": query}),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                body = r.read()
            json.loads(body)  # must be JSON, not an HTML error page
            return body
        except Exception as e:  # noqa: BLE001 - retry on any network / server error
            last = e
            wait = 15 * (i + 1)
            print(f"  attempt {i + 1} via {url} failed ({e}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Overpass failed after {attempts} attempts: {last}")


def main(which: str = "all") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["# OpenStreetMap extracts", "", "Licence: ODbL 1.0, © OpenStreetMap contributors.", f"BBox: `{BBOX}`", ""]
    for name, q in QUERIES.items():
        if which not in ("all", name):
            continue
        body = fetch(q)
        path = OUT / f"{name}_raw.json"
        path.write_bytes(body)
        n = len(json.loads(body)["elements"])
        sha = hashlib.sha256(body).hexdigest()[:16]
        now = f"{dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M}"
        lines.append(f"- `{path.name}`: {n} elements, sha256 {sha}…, fetched {now} UTC")
        print(f"{name}: {n} elements -> {path}")
    (OUT / "SOURCE.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
