"""Build the segmentation training set: real (Pothole Mix) + synthetic (rendered passes) -> one folder.

Classes: 0 = background, 1 = damage (pothole / edge break / depression), 255 = ignore (cracks: they are
not area damage and would otherwise teach the model to call every crack a pothole).

Real     : Pothole Mix v2 splits (training -> train, validation -> val_real, testing -> test_real).
           Images resized so the long side is <= 1024 px.
Synthetic: seed-07 passes, frames with stored truth (every 5th frame). Only the road band of the frame is
           kept (rows 400-912 of 1080: horizon margin to bonnet), resized to 960x256 — the exact strip
           `perception/segment.py` feeds the model. Hold-out by *road stretch*, not by frame: clips 08-09
           (~4.6 km) are val_synth, so no validation defect is ever seen in training.
           Negatives (truth frames with no defect visible, incl. shadows, wet patches, repairs) are sampled
           at `--neg-ratio` x positives.

Usage: uv run python -m training.prepare --synth data/synth/seed07 --out data/train/v1
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STRIP = (400, 912)  # rows of the 1080p frame fed to the model
STRIP_SIZE = (960, 256)
PMIX_SPLITS = {"training": "train", "validation": "val_real", "testing": "test_real"}
VAL_CLIPS = {8, 9}


def pmix_mask(bgr_mask: np.ndarray) -> np.ndarray:
    b, g, r = (bgr_mask[..., i].astype(np.int16) for i in range(3))
    out = np.zeros(bgr_mask.shape[:2], np.uint8)
    out[(g > 127) & (r < 128)] = 255  # crack -> ignore
    out[(r > 127) & (g < 128)] = 1  # pothole -> damage
    return out


def strip(img: np.ndarray, interp: int) -> np.ndarray:
    return cv2.resize(img[STRIP[0] : STRIP[1]], STRIP_SIZE, interpolation=interp)


def add_pothole_mix(src: Path, out: Path, splits: dict[str, list[str]]) -> None:
    for folder, split in PMIX_SPLITS.items():
        for img_path in sorted((src / folder).glob("*/images/*")):
            sub = img_path.parent.parent.name
            mask_path = next(iter(sorted(img_path.parent.parent.glob(f"masks/{img_path.stem}.*"))), None)
            if mask_path is None:
                continue
            img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)  # applies EXIF orientation (crack500)
            m = cv2.imread(str(mask_path), cv2.IMREAD_COLOR)
            if img is None or m is None:
                continue
            if m.shape[:2] != img.shape[:2]:
                m = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
            s = min(1024 / max(img.shape[:2]), 1.0)
            if s < 1:
                img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                m = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
            name = f"pmix__{sub}__{img_path.stem}"
            cv2.imwrite(str(out / "images" / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 93])
            cv2.imwrite(str(out / "masks" / f"{name}.png"), pmix_mask(m))
            splits[split].append(name)


def add_synthetic(seed_dir: Path, out: Path, splits: dict[str, list[str]], neg_ratio: float, every: int) -> None:
    rng = random.Random(0)
    for pass_dir in sorted(seed_dir.glob("pass_*")):
        masks = {}
        for mp in (pass_dir / "truth" / "masks").glob("clip*_*.png"):
            c, f = re.match(r"clip(\d+)_(\d+)", mp.stem).groups()
            masks[(int(c), int(f))] = mp
        for clip_dir in sorted(pass_dir.glob("clip_*")):
            ci = int(clip_dir.name.split("_")[1])
            meta = json.loads((clip_dir / "meta.json").read_text())
            n = meta["frames"]
            pos = [f for f in range(0, n, 5) if (ci, f) in masks][::every]
            neg_all = [f for f in range(0, n, 5) if (ci, f) not in masks]
            neg = set(rng.sample(neg_all, min(len(neg_all), int(len(pos) * neg_ratio))))
            want = set(pos) | neg
            split = "val_synth" if ci in VAL_CLIPS else "train"
            cap = cv2.VideoCapture(str(clip_dir / "clip.mp4"))
            for f in range(max(want) + 1 if want else 0):
                ok, frame = cap.read()
                if not ok:
                    break
                if f not in want:
                    continue
                inst = cv2.imread(str(masks[(ci, f)]), cv2.IMREAD_UNCHANGED) if (ci, f) in masks else None
                lbl = (inst > 0).astype(np.uint8) if inst is not None else np.zeros(frame.shape[:2], np.uint8)
                name = f"synth__{seed_dir.name}_{pass_dir.name}_c{ci:02d}_{f:06d}"
                jpg = [cv2.IMWRITE_JPEG_QUALITY, 93]
                cv2.imwrite(str(out / "images" / f"{name}.jpg"), strip(frame, cv2.INTER_AREA), jpg)
                cv2.imwrite(str(out / "masks" / f"{name}.png"), strip(lbl, cv2.INTER_NEAREST))
                splits[split].append(name)
            cap.release()
            print(f"{pass_dir.name}/{clip_dir.name}: {len(pos)} positive, {len(neg)} negative -> {split}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pmix", type=Path, default=ROOT / "data" / "raw" / "pothole_mix" / "pothole-mix")
    ap.add_argument("--synth", type=Path, nargs="*", default=[ROOT / "data" / "synth" / "seed07"])
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "train" / "v1")
    ap.add_argument("--merge", type=Path, nargs="*", default=[], help="already prepared sets to fold in (by split)")
    ap.add_argument("--neg-ratio", type=float, default=0.5)
    ap.add_argument("--every", type=int, default=2, help="keep every Nth positive truth frame (they are 5 apart)")
    args = ap.parse_args()
    (args.out / "images").mkdir(parents=True, exist_ok=True)
    (args.out / "masks").mkdir(parents=True, exist_ok=True)
    splits: dict[str, list[str]] = {"train": [], "val_real": [], "test_real": [], "val_synth": []}
    if args.pmix.exists():
        add_pothole_mix(args.pmix, args.out, splits)
    for md in args.merge:
        for sub in ("images", "masks"):
            for f in (md / sub).iterdir():
                dst = args.out / sub / f.name
                if not dst.exists():
                    dst.hardlink_to(f) if f.stat().st_dev == args.out.stat().st_dev else dst.write_bytes(f.read_bytes())
        for k, v in json.loads((md / "splits.json").read_text()).items():
            splits.setdefault(k, []).extend(v)
    for sd in args.synth:
        add_synthetic(sd, args.out, splits, args.neg_ratio, args.every)
    (args.out / "splits.json").write_text(json.dumps(splits))
    (args.out / "README.md").write_text(
        "# Patchwork segmentation set v1\n\nClasses: 0 background, 1 damage, 255 ignore (cracks).\n"
        "Sources: Pothole Mix v2 (CC BY-NC 3.0 / per-source licences, research use) + Patchwork synthetic.\n\n"
        + "\n".join(f"- {k}: {len(v)}" for k, v in splits.items())
        + "\n"
    )
    print({k: len(v) for k, v in splits.items()})


if __name__ == "__main__":
    main()
