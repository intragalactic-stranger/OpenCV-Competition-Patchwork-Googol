"""Train the damage segmenter. CPU on Graviton Spot via AWS Batch (D-25), or GPU on SageMaker (D-31).

Model : SegFormer (HF `nvidia/mit-b0` by default, `--backbone nvidia/mit-b2` on GPU; NVIDIA research licence,
        see D-07/D-24) or
        `--arch lraspp` (torchvision LR-ASPP MobileNetV3-Large, BSD weights: the licence-clean fallback).
Data  : training/prepare.py output (images/, masks/, splits.json); classes 0 bg, 1 damage, 255 ignore.
Loss  : cross-entropy (ignore 255, damage weight 2) + soft Dice on the damage class.
Spot  : a checkpoint is written every epoch (and synced to --s3-out); a restarted job resumes from it.
Output: best.pt, model.onnx (logits only, dynamic H/W, opset 17), metrics.json, class_map.json.

  uv run --group train python -m training.train --data data/train/v1 --out runs/dev --epochs 1 --limit 64
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader, Dataset

MEAN = np.array([0.485, 0.456, 0.406], np.float32) * 255
STD = np.array([0.229, 0.224, 0.225], np.float32) * 255
CLASSES = ["background", "damage"]


# ---------------------------------------------------------------- data
class SegSet(Dataset):
    def __init__(self, root: Path, names: list[str], train: bool, crop: tuple[int, int] = (512, 256)):
        self.root, self.names, self.train, self.crop = root, names, train, crop

    def __len__(self) -> int:
        return len(self.names)

    def _load(self, i: int) -> tuple[np.ndarray, np.ndarray]:
        n = self.names[i]
        img = cv2.imread(str(self.root / "images" / f"{n}.jpg"), cv2.IMREAD_COLOR)
        m = cv2.imread(str(self.root / "masks" / f"{n}.png"), cv2.IMREAD_UNCHANGED)
        return img, m

    def _augment(self, img: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cw, ch = self.crop
        # scale so the crop sees 35-100 % of the image width, never smaller than the crop
        s = random.uniform(0.35, 1.0) * img.shape[1] / cw
        s = max(1 / s, cw / img.shape[1], ch / img.shape[0])
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        m = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        # damage-biased crop: half the time centre the crop on a damage pixel
        ys, xs = np.nonzero(m == 1)
        if len(ys) and random.random() < 0.5:
            k = random.randrange(len(ys))
            x0 = int(np.clip(xs[k] - cw // 2 + random.randint(-cw // 4, cw // 4), 0, img.shape[1] - cw))
            y0 = int(np.clip(ys[k] - ch // 2 + random.randint(-ch // 4, ch // 4), 0, img.shape[0] - ch))
        else:
            x0 = random.randint(0, img.shape[1] - cw)
            y0 = random.randint(0, img.shape[0] - ch)
        img, m = img[y0 : y0 + ch, x0 : x0 + cw], m[y0 : y0 + ch, x0 : x0 + cw]
        if random.random() < 0.5:
            img, m = img[:, ::-1], m[:, ::-1]
        # photometric: exposure, contrast, colour cast, blur, noise, JPEG
        f = img.astype(np.float32)
        f = (f - 128) * random.uniform(0.7, 1.3) + 128 + random.uniform(-30, 30)
        f *= np.array([random.uniform(0.9, 1.1) for _ in range(3)], np.float32)
        if random.random() < 0.3:
            f = cv2.GaussianBlur(f, (0, 0), random.uniform(0.5, 1.5))
        if random.random() < 0.3:
            f += np.random.normal(0, random.uniform(2, 8), f.shape).astype(np.float32)
        img = np.clip(f, 0, 255).astype(np.uint8)
        if random.random() < 0.3:
            _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, random.randint(40, 90)])
            img = cv2.imdecode(enc, cv2.IMREAD_COLOR)
        return np.ascontiguousarray(img), np.ascontiguousarray(m)

    def __getitem__(self, i: int):
        img, m = self._load(i)
        if self.train:
            img, m = self._augment(img, m)
        else:
            img, m = eval_resize(img, m)
        return to_tensor(img), torch.from_numpy(m.astype(np.int64))


def eval_resize(img: np.ndarray, m: np.ndarray | None = None, width: int | None = None):
    """Resize to `width` keeping aspect (dashcam strips stay at 1440 px, others 960), pad H to a multiple of 32."""
    from patchwork.perception.segment import model_width

    width = width or model_width(img)
    s = width / img.shape[1]
    h = int(round(img.shape[0] * s))
    img = cv2.resize(img, (width, h), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    ph = (32 - h % 32) % 32
    img = cv2.copyMakeBorder(img, 0, ph, 0, 0, cv2.BORDER_CONSTANT, value=0)
    if m is None:
        return img
    m = cv2.resize(m, (width, h), interpolation=cv2.INTER_NEAREST)
    m = cv2.copyMakeBorder(m, 0, ph, 0, 0, cv2.BORDER_CONSTANT, value=255)
    return img, m


def to_tensor(bgr: np.ndarray) -> torch.Tensor:
    rgb = (bgr[..., ::-1].astype(np.float32) - MEAN) / STD
    return torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1)))


# ---------------------------------------------------------------- model
class SegFormerLogits(nn.Module):
    """HF SegFormer returning plain logits at 1/4 resolution (ONNX-friendly)."""

    def __init__(self, pretrained: str = "nvidia/mit-b0"):
        super().__init__()
        from transformers import SegformerForSemanticSegmentation

        self.net = SegformerForSemanticSegmentation.from_pretrained(
            pretrained,
            num_labels=len(CLASSES),
            id2label=dict(enumerate(CLASSES)),
            label2id={c: i for i, c in enumerate(CLASSES)},
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(pixel_values=x).logits


class LRASPPLogits(nn.Module):
    def __init__(self):
        super().__init__()
        from torchvision.models import MobileNet_V3_Large_Weights
        from torchvision.models.segmentation import lraspp_mobilenet_v3_large

        self.net = lraspp_mobilenet_v3_large(
            weights=None, weights_backbone=MobileNet_V3_Large_Weights.IMAGENET1K_V2, num_classes=len(CLASSES)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)["out"]


def build(arch: str, backbone: str = "nvidia/mit-b0") -> nn.Module:
    return SegFormerLogits(backbone) if arch == "segformer" else LRASPPLogits()


def loss_fn(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    logits = F.interpolate(logits, size=target.shape[-2:], mode="bilinear", align_corners=False)
    ce = F.cross_entropy(logits, target, weight=torch.tensor([1.0, 2.0], device=logits.device), ignore_index=255)
    valid = (target != 255).float()
    p = logits.softmax(1)[:, 1] * valid
    t = (target == 1).float() * valid
    dice = 1 - (2 * (p * t).sum() + 1) / (p.sum() + t.sum() + 1)
    return ce + dice


@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader) -> dict:
    model.eval()
    inter = union = 0
    tp_img = fn_img = fp_img = 0
    dev = next(model.parameters()).device
    for x, y in loader:
        x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
            out = model(x)
        logits = F.interpolate(out.float(), size=y.shape[-2:], mode="bilinear", align_corners=False)
        pred = logits.argmax(1)
        valid = y != 255
        p, t = (pred == 1) & valid, (y == 1) & valid
        inter += int((p & t).sum())
        union += int((p | t).sum())
        for pi, ti in zip(p, t, strict=True):
            has_p, has_t = bool(pi.sum() > 50), bool(ti.sum() > 0)
            tp_img += has_p and has_t
            fn_img += (not has_p) and has_t
            fp_img += has_p and not has_t
    model.train()
    return {
        "iou_damage": round(inter / max(union, 1), 4),
        "image_recall": round(tp_img / max(tp_img + fn_img, 1), 4),
        "image_fp": int(fp_img),
    }


# ---------------------------------------------------------------- export
def export_onnx(model: nn.Module, path: Path) -> None:
    model = model.cpu().eval()
    x = torch.randn(1, 3, 352, 1440)
    torch.onnx.export(
        model,
        x,
        str(path),
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {2: "h", 3: "w"}, "logits": {2: "h4", 3: "w4"}},
        opset_version=17,
        dynamo=False,
    )


def s3_sync(src: Path, dst: str | None) -> None:
    if dst:
        subprocess.run(["aws", "s3", "sync", str(src), dst, "--only-show-errors"], check=False)


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--data-s3", default=None, help="s3://bucket/prefix of the prepared set (synced to --data first)")
    ap.add_argument("--s3-out", default=None, help="s3://bucket/prefix to mirror checkpoints + outputs")
    ap.add_argument("--arch", choices=["segformer", "lraspp"], default="segformer")
    ap.add_argument("--backbone", default="nvidia/mit-b0", help="SegFormer encoder, e.g. nvidia/mit-b2")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--workers", type=int, default=max(os.cpu_count() // 4, 1))
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None, help="debug: cap images per split")
    ap.add_argument("--max-hours", type=float, default=6.0)
    ap.add_argument("--synth-weight", type=float, default=1.0, help="sampling weight of synthetic vs real")
    ap.add_argument(
        "--skip-opencv-eval",
        action="store_true",
        help="GPU jobs: skip the slow CPU evaluation through OpenCV (run training.evaluate on Batch)",
    )
    ap.add_argument(
        "--synthetic-only",
        action="store_true",
        help="licence-clean model: train on our synthetic frames only (no Pothole Mix), D-07",
    )
    ap.add_argument("--init", default=None, help="fine-tune: start from these weights (best.pt path or s3:// URI)")
    args = ap.parse_args()

    torch.set_num_threads(args.threads or max((os.cpu_count() or 4) - args.workers, 1))
    random.seed(0)
    torch.manual_seed(0)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.data_s3:
        subprocess.run(["aws", "s3", "sync", args.data_s3, str(args.data), "--only-show-errors"], check=True)
    if args.s3_out:  # resume after a Spot interruption
        subprocess.run(["aws", "s3", "sync", args.s3_out, str(args.out), "--only-show-errors"], check=False)
    splits = json.loads((args.data / "splits.json").read_text())
    if args.limit:
        splits = {k: v[: args.limit] for k, v in splits.items()}
    train_names = splits["train"]
    if args.synthetic_only:
        train_names = [n for n in train_names if n.startswith("synth__")]
        print(f"synthetic only: {len(train_names)} training images", flush=True)
    w = [args.synth_weight if n.startswith("synth__") else 1.0 for n in train_names]
    sampler = torch.utils.data.WeightedRandomSampler(w, num_samples=len(train_names), replacement=True)
    train_dl = DataLoader(
        SegSet(args.data, train_names, True),
        batch_size=args.batch,
        sampler=sampler,
        num_workers=args.workers,
        drop_last=True,
        persistent_workers=args.workers > 0,
    )
    val = {
        k: DataLoader(SegSet(args.data, splits[k], False), batch_size=1, num_workers=args.workers)
        for k in ("val_real", "val_synth", "hard_neg_val")
        if splits.get(k)
    }
    scored = ("val_real", "val_synth")  # model selection; hard_neg_val (no damage at all) is reported only

    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {dev}" + (f" ({torch.cuda.get_device_name(0)})" if dev.type == "cuda" else ""), flush=True)
    model = build(args.arch, args.backbone)
    if args.init:
        src = args.init
        if src.startswith("s3://"):
            subprocess.run(["aws", "s3", "cp", src, str(args.out / "init.pt"), "--only-show-errors"], check=True)
            src = str(args.out / "init.pt")
        model.load_state_dict(torch.load(src, map_location="cpu"))
        print(f"initialised from {args.init}", flush=True)
    model.to(dev)
    head = [p for n, p in model.named_parameters() if "decode_head" in n or "classifier" in n]
    head_ids = {id(p) for p in head}
    body = [p for p in model.parameters() if id(p) not in head_ids]
    opt = torch.optim.AdamW([{"params": body, "lr": args.lr}, {"params": head, "lr": args.lr * 10}], weight_decay=0.01)
    total = args.epochs * len(train_dl)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda it: (1 - min(it, total - 1) / total) ** 0.9)

    start_epoch, best, history = 0, -1.0, []
    ckpt = args.out / "last.pt"
    if ckpt.exists():
        st = torch.load(ckpt, map_location=dev, weights_only=False)
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        start_epoch, best, history = st["epoch"] + 1, st["best"], st["history"]
        print(f"resumed from epoch {st['epoch']}", flush=True)

    t0 = time.time()
    model.train()
    for epoch in range(start_epoch, args.epochs):
        te, run = time.time(), 0.0
        for it, (x, y) in enumerate(train_dl):
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
                out = model(x)
            loss = loss_fn(out.float(), y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            run = 0.98 * run + 0.02 * loss.item() if it else loss.item()
            if it % 20 == 0:
                sec = (time.time() - te) / (it + 1)
                print(f"epoch {epoch} it {it}/{len(train_dl)} loss {run:.4f} {sec:.2f} s/it", flush=True)
        metrics = {k: evaluate(model, dl) for k, dl in val.items()}
        sel = [m["iou_damage"] for k, m in metrics.items() if k in scored]
        score = float(np.mean(sel)) if sel else -float(run)
        history.append({"epoch": epoch, "loss": round(run, 4), "minutes": round((time.time() - te) / 60, 1), **metrics})
        print(json.dumps(history[-1]), flush=True)
        if score > best:
            best = score
            torch.save(model.state_dict(), args.out / "best.pt")
        torch.save(
            {
                "model": model.state_dict(),
                "opt": opt.state_dict(),
                "sched": sched.state_dict(),
                "epoch": epoch,
                "best": best,
                "history": history,
            },
            ckpt,
        )
        s3_sync(args.out, args.s3_out)
        per_epoch = (time.time() - t0) / (epoch + 1 - start_epoch)
        if time.time() - t0 + per_epoch > args.max_hours * 3600 and epoch + 1 < args.epochs:
            print("time budget reached: stopping early", flush=True)
            break

    model.load_state_dict(torch.load(args.out / "best.pt", map_location=dev))
    export_onnx(model, args.out / "model.onnx")
    # the numbers that matter are measured through the deployed runtime: OpenCV 5 DNN, not PyTorch
    from training.evaluate import evaluate_onnx
    from training.parity import run_parity

    parity = run_parity(args.out / "model.onnx", args.data)
    opencv_eval = None
    if not args.skip_opencv_eval:
        opencv_eval = evaluate_onnx(args.out / "model.onnx", args.data)
        (args.out / "eval_opencv.json").write_text(json.dumps(opencv_eval, indent=1))
    (args.out / "class_map.json").write_text(json.dumps({"classes": CLASSES, "ignore": 255}))
    (args.out / "metrics.json").write_text(
        json.dumps(
            {
                "arch": args.arch,
                "backbone": args.backbone if args.arch == "segformer" else None,
                "device": torch.cuda.get_device_name(0) if dev.type == "cuda" else "cpu",
                "best_score": best,
                "history": history,
                "train_images": len(train_names),
                "synthetic_only": bool(args.synthetic_only),
                "init": args.init,
                "input": "RGB, ImageNet mean/std, HxW multiple of 32; logits at 1/4 (segformer) or 1/1 (lraspp)",
                "hours": round((time.time() - t0) / 3600, 2),
                "parity": parity,
                "opencv_eval": opencv_eval,
            },
            indent=1,
        )
    )
    s3_sync(args.out, args.s3_out)
    print(f"done: best mean IoU {best:.4f}", flush=True)


if __name__ == "__main__":
    main()
