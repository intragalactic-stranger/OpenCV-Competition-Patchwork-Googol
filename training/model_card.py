"""Fill section 7 of docs/midpoint/07-MODEL-CARD.md from a finished training run, and publish the headline
numbers to eval/results/segmentation.json (read by eval/report.py for the midpoint results table).

  uv run python -m training.model_card s3://patchwork-<acct>-artifacts/models/seg-v1   (or a local run dir)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "midpoint" / "07-MODEL-CARD.md"
SPLIT_NAMES = {
    "test_real": "Real photos, held-out test split (Pothole Mix test)",
    "val_real": "Real photos, validation split (Pothole Mix val)",
    "val_synth": "Synthetic Mumbai dashcam strips, held-out road stretch",
}


def load_run(src: str) -> tuple[dict, str]:
    if src.startswith("s3://"):
        tmp = Path(tempfile.mkdtemp())
        for f in ("metrics.json", "parity.json", "eval_opencv.json"):
            subprocess.run(
                ["aws", "s3", "cp", f"{src.rstrip('/')}/{f}", str(tmp / f), "--only-show-errors"], check=False
            )
        d = tmp
    else:
        d = Path(src)
    m = json.loads((d / "metrics.json").read_text())
    return m, src


def render(m: dict, src: str) -> str:
    ev, par, hist = m.get("opencv_eval", {}), m.get("parity", {}), m.get("history", [])
    rows = [
        f"**Run:** `{src}` · architecture `{m['arch']}` · {m['train_images']} training images · "
        f"{len(hist)} epochs in {m['hours']} h on CPU · runtime engine for these numbers: **{ev.get('engine', '?')}**",
        "",
        "| Evaluation set (never used for training) | Images | IoU (damage) | Image recall "
        "| False-positive images | ms / image |",
        "|---|---|---|---|---|---|",
    ]
    for k, label in SPLIT_NAMES.items():
        if k in ev:
            e = ev[k]
            rows.append(
                f"| {label} | {e['images']} | **{e['iou_damage']:.3f}** | {e['image_recall']:.3f} | "
                f"{e['false_positive_images']} of {e['negative_images']} negatives | {e['ms_per_image']:.0f} |"
            )
    new, classic = par.get("ENGINE_NEW", {}), par.get("ENGINE_CLASSIC", {})
    rows += [
        "",
        "| OpenCV 5 runtime check (same images through both runtimes) | Result |",
        "|---|---|",
        f"| ENGINE_NEW loads the model | {'yes' if new.get('loaded') else 'NO'} |",
        f"| Max difference vs onnxruntime (logits) | {new.get('max_abs_diff', float('nan')):.1e} (target ≤ 1e-3) |",
        f"| Pixels with the same decision | {100 * new.get('argmax_agreement', 0):.4f}% |",
        f"| ENGINE_CLASSIC (OpenCV 4.x-style importer) | "
        f"{'also loads it' if classic.get('loaded') else 'cannot load it: ' + classic.get('error', '')[:90]} |",
        "",
        "Training curve (validation IoU after each epoch, measured in PyTorch):",
        "",
        "| Epoch | Train loss | IoU val_real | IoU val_synth | Minutes |",
        "|---|---|---|---|---|",
    ]
    for h in hist:
        vr = h.get("val_real", {}).get("iou_damage", "")
        vs = h.get("val_synth", {}).get("iou_damage", "")
        rows.append(f"| {h['epoch']} | {h['loss']} | {vr} | {vs} | {h['minutes']} |")
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    args = ap.parse_args()
    m, src = load_run(args.run)
    text = DOC.read_text()
    pat = re.compile(r"(<!-- MODEL-METRICS:BEGIN -->\n).*?(\n<!-- MODEL-METRICS:END -->)", re.S)
    DOC.write_text(pat.sub(lambda g: g.group(1) + render(m, src) + g.group(2), text))
    ev = m.get("opencv_eval", {})
    seg = {
        "run": src,
        "arch": m["arch"],
        "engine": ev.get("engine"),
        **{f"iou_{k}": ev[k]["iou_damage"] for k in SPLIT_NAMES if k in ev},
        **{f"images_{k}": ev[k]["images"] for k in SPLIT_NAMES if k in ev},
        "parity": m.get("parity", {}),
    }
    out = ROOT / "eval" / "results" / "segmentation.json"
    out.write_text(json.dumps(seg, indent=1))
    print(f"updated {DOC.relative_to(ROOT)} and {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
