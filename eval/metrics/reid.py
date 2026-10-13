"""Cross-pass re-identification preview (Phase 6 "verification", basic matcher).

The register links a pass-k detection to an existing defect if it lies on the same road segment within
LINK_M (8 m) of it (register/dataapi.py). Here the same rule is applied to pipeline outputs of two passes and
scored against the synthetic truth:
  link precision / recall / F1   a predicted link is correct if both detections match the same truth defect
  repaired recall                 truth defects repaired between the passes that the system no longer sees
                                  (pass-1 detection with no pass-2 detection within LINK_M)
  false "repaired"                defects still present but not re-detected (missed in pass 2)

  uv run python -m eval.metrics.reid data/synth/seed11 --runs runs/e2e --passes 1 2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.metrics.end_to_end import match_truth
from patchwork.register.dataapi import LINK_M

ROOT = Path(__file__).resolve().parents[2]


def load_pass(pass_dir: Path, run_root: Path) -> tuple[list[dict], list[dict], list[tuple[float, float]]]:
    det, covered = [], []
    for clip in sorted(pass_dir.glob("clip_*")):
        f = run_root / pass_dir.name / clip.name / "defects.json"
        if f.exists():
            det += json.loads(f.read_text())
            covered.append(tuple(json.loads((clip / "meta.json").read_text())["chainage_m"]))
    truth = json.loads((pass_dir / "truth" / "defects.json").read_text())
    return det, truth, covered


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seed_dir", type=Path)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--passes", type=int, nargs=2, default=[1, 2])
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "reid.json")
    args = ap.parse_args()
    a, b = (args.seed_dir / f"pass_{k}" for k in args.passes)
    det1, truth1, cov1 = load_pass(a, args.runs)
    det2, truth2, cov2 = load_pass(b, args.runs)

    def inside(s: float, cov) -> bool:
        return any(x + 12 <= s <= y for x, y in cov)

    vis1 = [t for t in truth1 if t["area_m2"] and abs(t["centroid_d"]) <= 4.5 and inside(t["centroid_s"], cov1)]
    vis2 = [t for t in truth2 if t["area_m2"] and abs(t["centroid_d"]) <= 4.5 and inside(t["centroid_s"], cov2)]
    m1 = {id(d): t["truth_id"] for d, t in match_truth(det1, vis1)[0]}
    m2 = {id(d): t["truth_id"] for d, t in match_truth(det2, vis2)[0]}

    # predicted links (register rule): nearest pass-1 detection on the same segment within LINK_M
    pred = []
    for d2 in det2:
        cands = [
            d1
            for d1 in det1
            if d1["segment_id"] == d2["segment_id"]
            and abs(d1["s"] - d2["s"]) <= LINK_M
            and abs(d1["d"] - d2["d"]) <= LINK_M
        ]
        if cands:
            pred.append((min(cands, key=lambda d1: abs(d1["s"] - d2["s"]) + abs(d1["d"] - d2["d"])), d2))
    tp = sum(1 for d1, d2 in pred if id(d1) in m1 and id(d2) in m2 and m1[id(d1)] == m2[id(d2)])
    t1 = {}
    for d1 in det1:
        if id(d1) in m1:
            t1.setdefault(m1[id(d1)], d1)
    true_pairs = sum(1 for d2 in det2 if id(d2) in m2 and m2[id(d2)] in t1)
    precision = tp / max(len(pred), 1)
    recall = tp / max(true_pairs, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    # repaired between passes: truth state repaired in pass 2, detected in pass 1
    state2 = {t["truth_id"]: t["state"] for t in truth2}
    seen2 = [d2 for d2 in det2]

    def resighted(d1: dict) -> bool:
        return any(d2["segment_id"] == d1["segment_id"] and abs(d2["s"] - d1["s"]) <= LINK_M for d2 in seen2)

    rep = [d1 for d1 in det1 if id(d1) in m1 and state2.get(m1[id(d1)]) == "repaired" and inside(d1["s"], cov2)]
    still = [
        d1
        for d1 in det1
        if id(d1) in m1 and state2.get(m1[id(d1)]) in ("present", "degraded") and inside(d1["s"], cov2)
    ]
    res = {
        "passes": args.passes,
        "link_rule_m": LINK_M,
        "predicted_links": len(pred),
        "correct_links": tp,
        "true_pairs_detected_in_both": true_pairs,
        "link_precision": round(precision, 3),
        "link_recall": round(recall, 3),
        "link_f1": round(f1, 3),
        "repaired_in_truth_and_detected_in_pass1": len(rep),
        "repaired_recall": round(sum(not resighted(d) for d in rep) / max(len(rep), 1), 3),
        "still_present_but_not_resighted": sum(not resighted(d) for d in still),
        "still_present_detected_in_pass1": len(still),
    }
    print(json.dumps(res, indent=1))
    args.out.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
