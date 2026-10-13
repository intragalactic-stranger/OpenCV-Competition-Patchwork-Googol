"""Same look-alike frames (no damage in them) through seg-v2 and seg-v3: what the hard-negative fine-tune changed.
-> docs/midpoint/assets/hard_neg_compare.jpg

  uv run python scripts/figures/hard_neg_compare.py --before runs/seg-v2/model.onnx --after runs/seg-v3/model.onnx \
      --data data/train/v3-hardval
Top row = before (seg-v2), bottom row = after (seg-v3). Red = pixels the model calls damage; every red pixel here is
a false positive. The last column is a frame both models still get wrong, shown on purpose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from patchwork.perception.segment import Segmenter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seg_examples import panel  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--k", type=int, default=4, help="columns: k-1 fixed frames + 1 still wrong")
    args = ap.parse_args()
    seg_b, seg_a = Segmenter(args.before), Segmenter(args.after)
    names = json.loads((args.data / "splits.json").read_text())["hard_neg_val"]
    fixed, still = [], []
    for n in names:
        img = cv2.imread(str(args.data / "images" / f"{n}.jpg"))
        if img is None:
            continue
        gt = cv2.imread(str(args.data / "masks" / f"{n}.png"), cv2.IMREAD_UNCHANGED)
        gt = np.zeros(img.shape[:2], np.uint8) if gt is None else gt  # no mask file = no damage
        pb, pa = seg_b.predict(img, dashcam=False).mask, seg_a.predict(img, dashcam=False).mask
        if pb.any() and not pa.any():
            fixed.append((int(pb.sum()), n, img, gt, pb, pa))
        elif pb.any() and pa.any():
            still.append((int(pa.sum()), n, img, gt, pb, pa))
    print(f"flagged by before only: {len(fixed)}, by both: {len(still)}")
    fixed.sort(key=lambda x: -x[0])  # the largest false alarms seg-v3 removed
    still.sort(key=lambda x: -x[0])
    chosen = fixed[: args.k - 1] + still[:1]
    top = [panel(img, gt, pb, f"seg-v2: {pb.sum()} px flagged") for _, _, img, gt, pb, _ in chosen]
    bot = [
        panel(img, gt, pa, f"seg-v3: {pa.sum()} px flagged" + (" (still wrong)" if i == len(chosen) - 1 else ""))
        for i, (_, _, img, gt, _, pa) in enumerate(chosen)
    ]

    def row(ps: list[np.ndarray]) -> np.ndarray:
        return np.hstack([cv2.copyMakeBorder(p, 0, 6, 0, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for p in ps])

    out = ROOT / "docs" / "midpoint" / "assets" / "hard_neg_compare.jpg"
    cv2.imwrite(str(out), np.vstack([row(top), row(bot)]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"wrote {out}; frames: {[c[1] for c in chosen]}")


if __name__ == "__main__":
    main()
