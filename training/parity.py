"""ONNX parity: OpenCV 5 DNN (ENGINE_NEW, then ENGINE_CLASSIC) vs onnxruntime on real inputs.

  uv run python -m training.parity runs/<version>/model.onnx --data data/train/v1 [--n 50]
Writes <model dir>/parity.json and eval/results/parity.json (feeds the midpoint results table).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from patchwork.perception.segment import preprocess

ROOT = Path(__file__).resolve().parents[1]
ENGINES = {"ENGINE_NEW": cv2.dnn.ENGINE_NEW, "ENGINE_CLASSIC": cv2.dnn.ENGINE_CLASSIC}


def run_parity(model: Path, data: Path, n: int = 50) -> dict:
    splits = json.loads((data / "splits.json").read_text())
    names = (splits.get("val_real", [])[: n // 2] + splits.get("val_synth", [])[: n // 2])[:n]
    names = names or splits["train"][:n]
    blobs = [preprocess(cv2.imread(str(data / "images" / f"{nm}.jpg"))) for nm in names]

    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    t = time.time()
    ref = [sess.run(None, {"input": b})[0] for b in blobs]
    ort_ms = 1000 * (time.time() - t) / len(blobs)
    out = {
        "model": model.name,
        "images": len(blobs),
        "input_shapes": sorted({str(b.shape) for b in blobs}),
        "onnxruntime_ms": round(ort_ms, 1),
        "opencv": cv2.__version__,
    }
    for name, eng in ENGINES.items():
        try:
            net = cv2.dnn.readNetFromONNX(str(model), eng)
            diffs, agree = [], []
            t = time.time()
            for b, r in zip(blobs, ref, strict=True):
                net.setInput(b)
                y = net.forward()
                diffs.append(float(np.abs(y - r).max()))
                agree.append(float((y.argmax(1) == r.argmax(1)).mean()))
            out[name] = {
                "loaded": True,
                "max_abs_diff": max(diffs),
                "argmax_agreement": round(float(np.mean(agree)), 6),
                "ms_per_image": round(1000 * (time.time() - t) / len(blobs), 1),
            }
        except Exception as e:  # record, never block the pipeline (decision D-15)
            out[name] = {"loaded": False, "error": str(e).splitlines()[0][:300] if str(e) else type(e).__name__}
        print(name, out[name], flush=True)
    (model.parent / "parity.json").write_text(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path)
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "train" / "v1")
    ap.add_argument("--n", type=int, default=50)
    args = ap.parse_args()
    out = run_parity(args.model, args.data, args.n)
    res = ROOT / "eval" / "results" / "parity.json"
    res.parent.mkdir(parents=True, exist_ok=True)
    res.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
