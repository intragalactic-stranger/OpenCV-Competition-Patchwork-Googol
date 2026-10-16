"""External check on REAL Indian road photos: RDD2022-India (Arya et al., CC BY-SA 4.0), never used for training.

RDD2022 has boxes, not masks, so this is a box-level check of the segmentation model run through OpenCV 5:
  pothole images   images annotated with at least one D40 (pothole) box
    image recall     the model marks damage overlapping a D40 box
    box recall       share of D40 boxes overlapped by predicted damage (>= 10 % of the box area, or >= 300 px)
  clean images     images with no annotation at all
    false-alarm images  the model marks any damage (>= 300 px)
Cracks (D00/D10/D20) are 'ignore' for our model by design, so images with only cracks are left out.
A fixed, sorted sample (every k-th file) keeps the run reproducible.

  uv run python -m eval.metrics.rdd_india --model runs/seg-v4/model.onnx [--n 300]
"""

from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2

from patchwork.perception.segment import Segmenter

ROOT = Path(__file__).resolve().parents[2]
RDD = ROOT / "data" / "raw" / "rdd2022_india" / "India" / "train"
MIN_PX = 300


def boxes(xml: Path) -> list[tuple[str, int, int, int, int]]:
    out = []
    for o in ET.parse(xml).getroot().iter("object"):
        b = o.find("bndbox")
        out.append((o.find("name").text, *(int(float(b.find(k).text)) for k in ("xmin", "ymin", "xmax", "ymax"))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--n", type=int, default=300, help="images per group")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "rdd_india.json")
    args = ap.parse_args()
    pot, clean = [], []
    for x in sorted((RDD / "annotations" / "xmls").glob("*.xml")):
        b = boxes(x)
        if any(n == "D40" for n, *_ in b):
            pot.append((x.stem, [bb for bb in b if bb[0] == "D40"]))
        elif not b:
            clean.append((x.stem, []))
    pick = lambda xs: xs[:: max(len(xs) // args.n, 1)][: args.n]  # noqa: E731
    pot, clean = pick(pot), pick(clean)
    seg = Segmenter(args.model)
    t0 = time.time()
    img_hit = box_hit = n_box = 0
    fa = 0
    per = []
    for stem, bbs in pot + clean:
        img = cv2.imread(str(RDD / "images" / f"{stem}.jpg"))
        m = seg.predict(img).mask.astype(bool)
        if bbs:
            hits = [
                (a := m[y0:y1, x0:x1].sum()) >= MIN_PX or a >= 0.1 * max((x1 - x0) * (y1 - y0), 1)
                for _, x0, y0, x1, y1 in bbs
            ]
            box_hit += sum(hits)
            n_box += len(hits)
            img_hit += any(hits)
            per.append({"image": stem, "d40_boxes": len(bbs), "hit": int(sum(hits))})
        else:
            flagged = int(m.sum() >= MIN_PX)
            fa += flagged
            per.append({"image": stem, "clean": True, "flagged": flagged})
    res = {
        "dataset": "RDD2022 India, train split (not used for training), CC BY-SA 4.0",
        "model": str(args.model),
        "engine": "OpenCV 5 ENGINE_NEW",
        "pothole_images": len(pot),
        "image_recall": round(img_hit / max(len(pot), 1), 3),
        "d40_boxes": n_box,
        "box_recall": round(box_hit / max(n_box, 1), 3),
        "clean_images": len(clean),
        "false_alarm_images": fa,
        "false_alarm_rate": round(fa / max(len(clean), 1), 3),
        "seconds_per_image": round((time.time() - t0) / max(len(per), 1), 2),
        "rows": per,
    }
    args.out.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
