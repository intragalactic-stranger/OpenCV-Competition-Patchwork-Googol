"""Survey corridor from OpenStreetMap: the real Mumbai loop the proposal drives.

Marine Drive -> Mumbai Coastal Road (control section, tunnels) -> Prabhadevi -> Worli Seaface
-> Dr Annie Besant Road -> Haji Ali -> Warden / Pedder Road -> back to Marine Drive.

The loop is routed on a directed OSM road graph (one-way rules respected) through waypoints that
are pinned to named roads. Output is an ordered polyline with per-vertex road attributes and
chainage, plus a list of contiguous road segments.

Data: OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import networkx as nx
import numpy as np
from pyproj import Transformer

# WGS84 <-> UTM 43N (Mumbai). All metric work happens in UTM.
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)

DRIVABLE = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}
# Routing cost multiplier: prefer the arterials a survey vehicle would actually use.
CLASS_COST = {
    "motorway": 0.8,
    "trunk": 0.9,
    "primary": 1.0,
    "secondary": 1.1,
    "tertiary": 1.4,
    "motorway_link": 1.0,
    "trunk_link": 1.0,
    "primary_link": 1.1,
    "secondary_link": 1.2,
    "tertiary_link": 1.4,
    "unclassified": 2.5,
    "residential": 3.0,
}
CONTROL_ROADS = {"Mumbai Coastal Road", "Mumbai Coastal Road - Phase I"}


@dataclass(frozen=True)
class Waypoint:
    label: str
    road: str  # OSM name the waypoint must sit on
    lat: float
    lon: float
    avoid_control: bool = False  # the leg arriving here may not use the Coastal Road (drive it once only)


# Ordered loop. Coordinates are approximate; each snaps to the nearest node on the named road.
DEFAULT_WAYPOINTS: tuple[Waypoint, ...] = (
    Waypoint("Marine Drive (Nariman Point end)", "Marine Drive", 18.9310, 72.8238),
    Waypoint("Marine Drive (Girgaon Chowpatty)", "Marine Drive", 18.9530, 72.8140),
    Waypoint("Coastal Road (Breach Candy)", "Mumbai Coastal Road", 18.9700, 72.8030),
    Waypoint("Coastal Road (Worli end)", "Mumbai Coastal Road - Phase I", 19.0095, 72.8150),
    Waypoint("Prabhadevi", "Prabhadevi New Road", 19.0150, 72.8200),
    Waypoint("Worli Seaface (north)", "Khan Abdul Gaffar Khan Marg", 19.0120, 72.8165),
    Waypoint("Worli Seaface (south)", "Khan Abdul Gaffar Khan Marg", 18.9960, 72.8125),
    Waypoint("Dr Annie Besant Road (Haji Ali)", "Dr Annie Besant Road", 18.9890, 72.8150),
    Waypoint("Warden Road", "Warden Road (Bhula Bhai Desai Marg)", 18.9700, 72.8060, avoid_control=True),
    Waypoint("Marine Drive (Chowpatty, southbound)", "Marine Drive", 18.9500, 72.8160, avoid_control=True),
    Waypoint("Marine Drive (Nariman Point end)", "Marine Drive", 18.9310, 72.8238, avoid_control=True),
)


@dataclass
class Segment:
    segment_id: str
    name: str
    highway: str
    is_control: bool
    is_tunnel: bool
    chainage_start_m: float
    chainage_end_m: float

    @property
    def length_m(self) -> float:
        return self.chainage_end_m - self.chainage_start_m


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


def build_graph(osm_json: dict) -> nx.DiGraph:
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm_json["elements"] if e["type"] == "node"}
    g = nx.DiGraph()
    for e in osm_json["elements"]:
        tags = e.get("tags", {})
        if e["type"] != "way" or tags.get("highway") not in DRIVABLE:
            continue
        hw = tags["highway"]
        oneway = tags.get("oneway", "yes" if hw in ("motorway", "motorway_link") else "no")
        attrs = {
            "name": tags.get("name", ""),
            "highway": hw,
            "tunnel": tags.get("tunnel", "no") not in ("no", ""),
            "way_id": e["id"],
            "lanes": tags.get("lanes"),
        }
        ids = [i for i in e["nodes"] if i in nodes]
        for u, v in zip(ids, ids[1:], strict=False):
            length = _haversine_m(nodes[u], nodes[v])
            w = length * CLASS_COST[hw]
            if oneway == "-1":
                u, v = v, u
            g.add_edge(u, v, length=length, weight=w, **attrs)
            if oneway not in ("yes", "true", "1", "-1"):
                g.add_edge(v, u, length=length, weight=w, **attrs)
    for n in g.nodes:
        g.nodes[n]["lat"], g.nodes[n]["lon"] = nodes[n]
    # Keep only the largest strongly connected component: roads clipped by the download bbox
    # (e.g. the Coastal Road running on to the Sea Link) are dead ends a loop must never enter.
    core = max(nx.strongly_connected_components(g), key=len)
    return g.subgraph(core).copy()


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Planar bearing (rad, 0 = east, CCW) from a to b, both (lat, lon)."""
    return math.atan2(b[0] - a[0], (b[1] - a[1]) * math.cos(math.radians(a[0])))


def snap_waypoint(g: nx.DiGraph, wp: Waypoint, heading: float | None = None, max_turn_deg: float = 60.0) -> int:
    """Nearest node on the named road. With `heading`, only edges travelling roughly that way count,
    so a waypoint on a dual carriageway lands on the correct side instead of forcing a U-turn."""
    best, best_d = None, float("inf")
    for u, v, a in g.edges(data=True):
        if a["name"] != wp.road:
            continue
        pu, pv = (g.nodes[u]["lat"], g.nodes[u]["lon"]), (g.nodes[v]["lat"], g.nodes[v]["lon"])
        if heading is not None:
            diff = abs((_bearing(pu, pv) - heading + math.pi) % (2 * math.pi) - math.pi)
            if math.degrees(diff) > max_turn_deg:
                continue
        d = _haversine_m((wp.lat, wp.lon), pv)
        if d < best_d:
            best, best_d = v, d
    if best is None:
        raise ValueError(f"no OSM road named {wp.road!r} (in that direction) for waypoint {wp.label!r}")
    if best_d > 400:
        raise ValueError(f"waypoint {wp.label!r} is {best_d:.0f} m from {wp.road!r}; fix its coordinates")
    return best


def _headings(waypoints: tuple[Waypoint, ...]) -> list[float]:
    """Direction of travel at each waypoint: departure heading for the first, arrival heading for the
    last, and previous -> next for the ones in between."""
    pts = [(w.lat, w.lon) for w in waypoints]
    n = len(pts)
    return [
        _bearing(pts[max(i - 1, 0)] if i else pts[0], pts[min(i + 1, n - 1)])
        if 0 < i < n - 1
        else _bearing(pts[0], pts[1])
        if i == 0
        else _bearing(pts[-2], pts[-1])
        for i in range(n)
    ]


def route_loop(g: nx.DiGraph, waypoints: tuple[Waypoint, ...] = DEFAULT_WAYPOINTS) -> list[int]:
    snapped = [snap_waypoint(g, wp, h) for wp, h in zip(waypoints, _headings(waypoints), strict=True)]
    no_control = nx.subgraph_view(g, filter_edge=lambda u, v: g.edges[u, v]["name"] not in CONTROL_ROADS)
    path: list[int] = [snapped[0]]
    for a, b, wa, wb in zip(snapped, snapped[1:], waypoints, waypoints[1:], strict=False):
        try:
            leg = nx.shortest_path(no_control if wb.avoid_control else g, a, b, weight="weight")
        except nx.NetworkXNoPath as e:
            raise ValueError(f"no drivable path {wa.label} -> {wb.label}") from e
        path.extend(leg[1:])
    return path


@dataclass
class Corridor:
    lat: np.ndarray  # (N,)
    lon: np.ndarray
    x: np.ndarray  # UTM 43N metres
    y: np.ndarray
    s: np.ndarray  # chainage along the loop, metres
    edge_name: list[str]  # attributes of the edge leaving vertex i (len N-1)
    edge_highway: list[str]
    edge_tunnel: list[bool]
    segments: list[Segment]

    @property
    def length_m(self) -> float:
        return float(self.s[-1])

    def segment_at(self, s: float) -> Segment:
        for seg in self.segments:
            if seg.chainage_start_m <= s < seg.chainage_end_m:
                return seg
        return self.segments[-1]

    def pose_at(self, s: float) -> tuple[float, float, float]:
        """(x, y, heading_rad) in UTM at chainage s; heading 0 = east, CCW positive."""
        s = float(np.clip(s, 0.0, self.length_m))
        i = int(np.clip(np.searchsorted(self.s, s, side="right") - 1, 0, len(self.s) - 2))
        t = (s - self.s[i]) / max(self.s[i + 1] - self.s[i], 1e-9)
        x = self.x[i] + t * (self.x[i + 1] - self.x[i])
        y = self.y[i] + t * (self.y[i + 1] - self.y[i])
        return x, y, math.atan2(self.y[i + 1] - self.y[i], self.x[i + 1] - self.x[i])


def _segments(s: np.ndarray, names: list[str], hws: list[str], tunnels: list[bool]) -> list[Segment]:
    segs: list[Segment] = []
    start = 0
    for i in range(1, len(names) + 1):
        if i == len(names) or (names[i], tunnels[i]) != (names[start], tunnels[start]):
            name = names[start] or f"unnamed {hws[start]}"
            segs.append(
                Segment(
                    segment_id=f"seg{len(segs):03d}",
                    name=name,
                    highway=hws[start],
                    is_control=names[start] in CONTROL_ROADS,
                    is_tunnel=tunnels[start],
                    chainage_start_m=float(s[start]),
                    chainage_end_m=float(s[i]),
                )
            )
            start = i
    return segs


def build_corridor(osm_json: dict, waypoints: tuple[Waypoint, ...] = DEFAULT_WAYPOINTS) -> Corridor:
    g = build_graph(osm_json)
    path = route_loop(g, waypoints)
    lat = np.array([g.nodes[n]["lat"] for n in path])
    lon = np.array([g.nodes[n]["lon"] for n in path])
    x, y = TO_UTM.transform(lon, lat)
    x, y = np.asarray(x), np.asarray(y)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    edges = [g.edges[u, v] for u, v in zip(path, path[1:], strict=False)]
    names = [e["name"] for e in edges]
    hws = [e["highway"] for e in edges]
    tunnels = [bool(e["tunnel"]) for e in edges]
    return Corridor(lat, lon, x, y, s, names, hws, tunnels, _segments(s, names, hws, tunnels))


def save_corridor(c: Corridor, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    line = {
        "type": "Feature",
        "properties": {
            "name": "Patchwork survey loop",
            "length_m": round(c.length_m, 1),
            "source": "OpenStreetMap contributors (ODbL)",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[float(a), float(b)] for a, b in zip(c.lon, c.lat, strict=True)],
        },
    }
    feats = []
    for seg in c.segments:
        idx = np.where((c.s >= seg.chainage_start_m) & (c.s <= seg.chainage_end_m))[0]
        coords = [[float(c.lon[i]), float(c.lat[i])] for i in idx]
        if len(coords) >= 2:
            feats.append(
                {
                    "type": "Feature",
                    "properties": {**asdict(seg), "length_m": round(seg.length_m, 1)},
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )
    (out_dir / "corridor.geojson").write_text(json.dumps(line))
    (out_dir / "segments.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    np.savez_compressed(
        out_dir / "corridor.npz",
        lat=c.lat,
        lon=c.lon,
        x=c.x,
        y=c.y,
        s=c.s,
        edge_name=np.array(c.edge_name),
        edge_highway=np.array(c.edge_highway),
        edge_tunnel=np.array(c.edge_tunnel),
    )
    (out_dir / "segments.json").write_text(json.dumps([asdict(s) for s in c.segments], indent=1))


def load_corridor(out_dir: Path) -> Corridor:
    z = np.load(out_dir / "corridor.npz")
    segs = [Segment(**d) for d in json.loads((out_dir / "segments.json").read_text())]
    return Corridor(
        z["lat"],
        z["lon"],
        z["x"],
        z["y"],
        z["s"],
        list(z["edge_name"]),
        list(z["edge_highway"]),
        [bool(t) for t in z["edge_tunnel"]],
        segs,
    )


POI_KINDS = {
    "school": "school",
    "college": "school",
    "university": "school",
    "kindergarten": "school",
    "hospital": "hospital",
    "clinic": "hospital",
    "bus_stop": "bus_stop",
    "platform": "bus_stop",
}


def corridor_pois(c: Corridor, poi_json: dict, max_dist_m: float = 200.0) -> list[dict]:
    """POIs within `max_dist_m` of the loop, each with its nearest chainage and distance."""
    out = []
    for e in poi_json["elements"]:
        tags = e.get("tags", {})
        kind = POI_KINDS.get(tags.get("amenity") or tags.get("highway") or ("platform" if tags.get("bus") else ""))
        if not kind:
            continue
        lat, lon = (e["lat"], e["lon"]) if "lat" in e else (e["center"]["lat"], e["center"]["lon"])
        x, y = TO_UTM.transform(lon, lat)
        d2 = (c.x - x) ** 2 + (c.y - y) ** 2
        i = int(np.argmin(d2))
        dist = float(np.sqrt(d2[i]))
        if dist <= max_dist_m:
            out.append(
                {
                    "poi_id": f"osm-{e['type']}-{e['id']}",
                    "kind": kind,
                    "name": tags.get("name", ""),
                    "lat": lat,
                    "lon": lon,
                    "chainage_m": round(float(c.s[i]), 1),
                    "dist_m": round(dist, 1),
                }
            )
    return sorted(out, key=lambda p: p["chainage_m"])


def save_pois(pois: list[dict], out_dir: Path) -> None:
    feats = [
        {
            "type": "Feature",
            "properties": {k: v for k, v in p.items() if k not in ("lat", "lon")},
            "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
        }
        for p in pois
    ]
    (out_dir / "poi.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
