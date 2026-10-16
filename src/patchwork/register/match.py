"""Cross-pass matching: is this detection a defect we already know? (Phase 6, verification v2.)

Geometry gates, chosen from physics rather than tuned on the evaluation set:
  along the road  |Δchainage| ≤ 12 m   localisation p90 is 6.5 m per pass, so two passes differ by up to ~2×
  across the road |Δoffset|   ≤ 1.5 m  the lateral offset comes from the camera geometry, not GNSS (p90 0.6 m)
  area ratio      ≤ 4×                  a degraded defect grows, but not from 0.1 to 1 m² in a week
Each new detection links to at most one known defect and vice versa (greedy on a cost, lowest first), so one
defect can never absorb two detections of the next pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LINK_S_M = 12.0
LINK_D_M = 1.5
LINK_AREA_RATIO = 4.0


@dataclass(frozen=True)
class Candidate:
    key: str  # defect id (register) or detection id
    segment_id: str
    s: float  # chainage, m
    d: float  # lateral offset, m
    area_m2: float | None


def cost(a: Candidate, b: Candidate) -> float | None:
    """Matching cost, or None if the pair fails a gate."""
    if a.segment_id != b.segment_id:
        return None
    ds, dd = abs(a.s - b.s), abs(a.d - b.d)
    if ds > LINK_S_M or dd > LINK_D_M:
        return None
    r = 0.5  # unknown area (detected, not measured): neutral
    if a.area_m2 and b.area_m2:
        r = abs(math.log(b.area_m2 / a.area_m2))
        if r > math.log(LINK_AREA_RATIO):
            return None
    return ds / 4.0 + dd / 0.4 + r


def assign(known: list[Candidate], new: list[Candidate]) -> dict[str, str]:
    """One-to-one links {new.key: known.key}, cheapest pairs first."""
    pairs = sorted(
        (c, k.key, n.key) for k in known for n in new if (c := cost(k, n)) is not None
    )
    used_k, out = set(), {}
    for _, kk, nk in pairs:
        if kk in used_k or nk in out:
            continue
        used_k.add(kk)
        out[nk] = kk
    return out
