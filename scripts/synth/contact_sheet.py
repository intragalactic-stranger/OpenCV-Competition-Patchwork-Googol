"""QA contact sheet: sampled frames from a synthetic clip with ground-truth defect masks outlined.

Usage: uv run python scripts/synth/contact_sheet.py data/synth/seed07/pass_1/clip_00 [--out path] [--n 8]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
COLORS = {"pothole": (40, 40, 230), "edge_break": (30, 180, 250), "depression": (230, 120, 40)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "main_docs" / "midpoint" / "assets" / "synth_contact_sheet.jpg")
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    pass_dir = args.clip_dir.parent
    clip_no = args.clip_dir.name.split("_")[1]
    defects = {d["index"]: d for d in json.loads((pass_dir / "truth" / "defects.json").read_text())}
    masks = sorted((pass_dir / "truth" / "masks").glob(f"clip{clip_no}_*.png"))
    # prefer frames where a defect is large in view
    scored = []
    for m in masks[::2]:
        inst = cv2.imread(str(m), cv2.IMREAD_UNCHANGED)
        scored.append((int((inst > 0).sum()), m))
    scored.sort(reverse=True)
    chosen, used = [], set()
    for _, m in scored:
        f = int(m.stem.split("_")[1])
        if all(abs(f - u) > 40 for u in used):
            chosen.append(m)
            used.add(f)
        if len(chosen) == args.n:
            break
    chosen.sort()
    cap = cv2.VideoCapture(str(args.clip_dir / "clip.mp4"))
    tiles = []
    for m in chosen:
        f = int(m.stem.split("_")[1])
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if not ok:
            continue
        inst = cv2.imread(str(m), cv2.IMREAD_UNCHANGED)
        over = img.copy()
        for idx in np.unique(inst[inst > 0]):
            d = defects.get(int(idx) - 1)
            if d is None:
                continue
            mk = (inst == idx).astype(np.uint8)
            cnts, _ = cv2.findContours(mk, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            col = COLORS[d["kind"]]
            cv2.drawContours(over, cnts, -1, col, 3)
            x, y, w, h = cv2.boundingRect(mk)
            if w * h > 300:
                label = f"{d['kind']} {d['area_m2']:.2f} m2"
                cv2.putText(over, label, (x, max(y - 10, 30)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 6, cv2.LINE_AA)
                cv2.putText(
                    over, label, (x, max(y - 10, 30)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA
                )
        both = np.hstack([img, over])
        cv2.putText(both, f"frame {f}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3, cv2.LINE_AA)
        tiles.append(cv2.resize(both, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA))
    if not tiles:
        raise SystemExit("no frames with ground-truth masks found")
    sheet = np.vstack(tiles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"{args.out} ({len(tiles)} rows: camera frame | ground truth)")


if __name__ == "__main__":
    main()
