"""Evaluate an exported model through the *deployed* path: OpenCV 5 DNN (ENGINE_NEW) + perception/segment.py.

Reports damage IoU, image-level recall and false-positive images per split (test_real, val_synth, ...).
  uv run python -m training.evaluate runs/<version>/model.onnx --data data/train/v1
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from patchwork.perception.segment import Segmenter


def evaluate_onnx(
    model: Path,
    data: Path,
    splits_wanted: tuple[str, ...] = ("test_real", "val_real", "val_synth", "hard_neg_val"),
    limit: int | None = None,
) -> dict:
    seg = Segmenter(model)
    splits = json.loads((data / "splits.json").read_text())
    out = {"engine": seg.engine}
    for split in splits_wanted:
        names = splits.get(split, [])[:limit]
        if not names:
            continue
        inter = union = tp = fn = fp = tn = 0
        t = time.time()
        for n in names:
            img = cv2.imread(str(data / "images" / f"{n}.jpg"))
            gt = cv2.imread(str(data / "masks" / f"{n}.png"), cv2.IMREAD_UNCHANGED)
            pred = seg.predict(img, dashcam=False).mask
            valid = gt != 255
            p, g = pred & valid, (gt == 1) & valid
            inter += int((p & g).sum())
            union += int((p | g).sum())
            has_p, has_g = bool(p.any()), bool(g.sum() > 0)
            tp += has_p and has_g
            fn += has_g and not has_p
            fp += has_p and not has_g
            tn += (not has_p) and not has_g
        out[split] = {
            "images": len(names),
            "iou_damage": round(inter / max(union, 1), 4),
            "image_recall": round(tp / max(tp + fn, 1), 4),
            "false_positive_images": fp,
            "negative_images": fp + tn,
            "ms_per_image": round(1000 * (time.time() - t) / len(names), 1),
        }
        print(split, out[split], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    res = evaluate_onnx(args.model, args.data, limit=args.limit)
    (args.model.parent / "eval_opencv.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
