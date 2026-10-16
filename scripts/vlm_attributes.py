"""VLM context attributes (Amazon Nova on Bedrock) for defect evidence images: evaluate, then write.

--eval   score water pooling and wheel path against the synthetic truth on pass-1 detections that match a
         true defect (evidence images from the cloud run), for one or more models
--write  describe every defect in the register (evidence image on the site bucket) and merge the answers into
         the latest observation's attributes, where the agent's exposure score reads them

uv run python scripts/vlm_attributes.py --eval --models apac.amazon.nova-lite-v1:0 apac.amazon.nova-pro-v1:0
uv run python scripts/vlm_attributes.py --write --model apac.amazon.nova-pro-v1:0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
from eval.metrics.end_to_end import match_truth
from eval.metrics.reid import load_pass

from patchwork.perception import vlm

ROOT = Path(__file__).resolve().parents[1]
ART = "patchwork-682839842398-artifacts"
SITE = "patchwork-682839842398-site"


def score(pairs: list[tuple[bool, bool]]) -> dict:
    tp = sum(p and t for p, t in pairs)
    fp = sum(p and not t for p, t in pairs)
    fn = sum(t and not p for p, t in pairs)
    acc = sum(p == t for p, t in pairs) / max(len(pairs), 1)
    return {
        "n": len(pairs),
        "accuracy": round(acc, 3),
        "precision": round(tp / max(tp + fp, 1), 3),
        "recall": round(tp / max(tp + fn, 1), 3),
        "positives_in_truth": sum(t for _, t in pairs),
    }


def evaluate(models: list[str]) -> dict:
    seed = ROOT / "data" / "synth" / "seed11"
    det, truth, cov = load_pass(seed / "pass_1", ROOT / "runs" / "e2e-v4")
    vis = [t for t in truth if t["area_m2"] and abs(t["centroid_d"]) <= 4.5]
    pairs = match_truth(det, vis)[0]
    s3 = boto3.client("s3", region_name=vlm.REGION)
    br = boto3.client("bedrock-runtime", region_name=vlm.REGION)
    out = {
        "what": "pass-1 detections of the final survey matched to a true defect; truth from the generator",
        "images": len(pairs),
    }
    for model in models:
        vlm.MODEL = model
        water, wheel, tokens, rows = [], [], 0, []
        for d, t in pairs:
            clip = d["defect_id"].split("-")[2].replace("clip", "clip_")
            key = f"runs/final-v4/pass_1/{clip}/overlays/{d['defect_id']}.jpg"
            img = s3.get_object(Bucket=ART, Key=key)["Body"].read()
            a = vlm.describe(img, br)
            tokens += a["vlm_tokens"]
            water.append((bool(a.get("water_pooling")), bool(t["attributes"]["water"])))
            wheel.append((bool(a.get("wheel_path")), bool(t["attributes"]["wheel_path"])))
            rows.append({"defect": d["defect_id"], "truth": t["attributes"], "vlm": a})
        out[model] = {"water_pooling": score(water), "wheel_path": score(wheel), "tokens": tokens, "rows": rows}
        print(model, json.dumps({k: out[model][k] for k in ("water_pooling", "wheel_path", "tokens")}), flush=True)
    return out


def write(model: str) -> int:
    from patchwork.register.dataapi import Register

    vlm.MODEL = model
    reg = Register()
    s3 = boto3.client("s3", region_name=vlm.REGION)
    br = boto3.client("bedrock-runtime", region_name=vlm.REGION)
    rows = reg.sql(
        "SELECT d.defect_id, o.obs_id, o.overlay_key, o.attributes::text AS attributes FROM defect d "
        "JOIN observation o ON o.obs_id = d.latest_obs_id"
    )
    n = 0
    for r in rows:
        try:
            img = s3.get_object(Bucket=SITE, Key=f"overlays/{r['overlay_key']}.jpg")["Body"].read()
        except s3.exceptions.NoSuchKey:
            continue
        a = vlm.describe(img, br)
        attrs = {**json.loads(r["attributes"] or "{}"), **{f"vlm_{k}": v for k, v in a.items()}}
        attrs["water_pooling"] = bool(a.get("water_pooling"))  # read by cluster_into_packages
        attrs["wheel_path"] = bool(a.get("wheel_path"))
        attrs["source"] = "rules+vlm"
        reg.sql(
            "UPDATE observation SET attributes = CAST(:a AS jsonb) WHERE obs_id = :o",
            {"a": json.dumps(attrs), "o": r["obs_id"]},
        )
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--models", nargs="+", default=[vlm.MODEL])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--model", default=vlm.MODEL)
    args = ap.parse_args()
    if args.eval:
        res = evaluate(args.models)
        (ROOT / "eval" / "results" / "vlm_attributes.json").write_text(json.dumps(res, indent=1))
    if args.write:
        print(f"described {write(args.model)} defects with {args.model}")


if __name__ == "__main__":
    main()
