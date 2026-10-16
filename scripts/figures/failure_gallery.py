"""Failure cases, side by side, for the final report (main_docs/submission/failure_gallery.jpg).

Row 1: synthetic survey (final run): two false alarms (no true defect within the match gate) and one fresh repair
       patch that the model still segments as damage (so the repair is reported as still present).
Row 2: REAL photos, RDD2022-India: pothole boxes (green) the model missed, with its damage mask in red. Faces and
       plates are blurred with the pipeline's own privacy step before the image is saved.

  uv run python scripts/figures/failure_gallery.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import boto3
import cv2
import numpy as np
from eval.metrics.end_to_end import match_truth
from eval.metrics.rdd_india import RDD, boxes
from eval.metrics.reid import load_pass

from patchwork.perception.privacy import Privacy
from patchwork.perception.segment import Segmenter

ROOT = Path(__file__).resolve().parents[2]
ART = "patchwork-682839842398-artifacts"
OUT = ROOT / "main_docs" / "submission" / "failure_gallery.jpg"
TILE_W, TILE_H = 560, 300


def tile(img: np.ndarray, title: str) -> np.ndarray:
    h, w = img.shape[:2]
    s = min(TILE_W / w, (TILE_H - 34) / h)
    im = cv2.resize(img, (int(w * s), int(h * s)))
    t = np.full((TILE_H, TILE_W, 3), 255, np.uint8)
    t[34 : 34 + im.shape[0], : im.shape[1]] = im
    cv2.putText(t, title, (6, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)
    return t


def overlay(key: str) -> np.ndarray:
    b = boto3.client("s3", region_name="ap-south-1").get_object(Bucket=ART, Key=key)["Body"].read()
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def key_of(defect_id: str, pass_name: str) -> str:
    clip = defect_id.split("-")[2].replace("clip", "clip_")
    return f"runs/final-v4/{pass_name}/{clip}/overlays/{defect_id}.jpg"


def main() -> None:
    seed = ROOT / "data" / "synth" / "seed11"
    det, truth, _ = load_pass(seed / "pass_2", ROOT / "runs" / "e2e-v4")
    vis = [t for t in truth if t["area_m2"] and abs(t["centroid_d"]) <= 4.5 and t["state"] != "repaired"]
    _, fps = match_truth(det, vis)
    repaired = [t for t in truth if t["state"] == "repaired"]

    def near_patch(d: dict) -> bool:
        return any(math.hypot(d["s"] - t["centroid_s"], d["d"] - t["centroid_d"]) < 3 for t in repaired)

    patch = [d for d in fps if near_patch(d) and d["area_m2"]]
    other = sorted((d for d in fps if not near_patch(d) and d["area_m2"]), key=lambda d: -d["area_m2"])
    row1 = [
        tile(overlay(key_of(other[0]["defect_id"], "pass_2")), "False alarm: no true defect within 12 m"),
        tile(overlay(key_of(other[1]["defect_id"], "pass_2")), "False alarm: look-alike flagged as damage"),
        tile(overlay(key_of(patch[0]["defect_id"], "pass_2")), "Repair patch still segmented as damage"),
    ]

    seg, priv = Segmenter(ROOT / "runs" / "seg-v4" / "model.onnx"), Privacy()
    res = json.loads((ROOT / "eval" / "results" / "rdd_india.json").read_text())
    missed = [r["image"] for r in res["rows"] if r.get("d40_boxes") and not r["hit"]][::25][:3]
    row2 = []
    for stem in missed:
        img = cv2.imread(str(RDD / "images" / f"{stem}.jpg"))
        m = seg.predict(img).mask.astype(bool)
        img = priv.apply(img).image
        img[m] = (0.5 * img[m] + 0.5 * np.array([0, 0, 255])).astype(np.uint8)
        for n, x0, y0, x1, y1 in boxes(RDD / "annotations" / "xmls" / f"{stem}.xml"):
            if n == "D40":
                cv2.rectangle(img, (x0, y0), (x1, y1), (0, 200, 0), 3)
        row2.append(tile(img, f"REAL (RDD2022-India {stem[-6:]}): pothole missed"))
    grid = np.vstack([np.hstack(row1), np.hstack(row2)])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT), grid, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
