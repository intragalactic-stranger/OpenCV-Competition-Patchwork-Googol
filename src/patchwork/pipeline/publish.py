"""Publish the register to the map viewer (S3 site bucket behind CloudFront).

Used by the Batch assemble job after every pass and by scripts/aws/deploy_viewer.py.
Configuration from arguments or env: PATCHWORK_SITE_BUCKET, PATCHWORK_CF_DISTRIBUTION, PATCHWORK_MAPS_KEY_NAME.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import boto3

from patchwork.register.dataapi import Register

ROOT = Path(__file__).resolve().parents[3]
REGION = "ap-south-1"


def maps_key(name: str) -> str:
    return boto3.client("location", region_name=REGION).describe_key(KeyName=name)["Key"]


def publish(
    overlay_dirs: list[Path] | None = None,
    source: str = "synthetic survey",
    bucket: str | None = None,
    distribution: str | None = None,
    key_name: str | None = None,
    register: Register | None = None,
    console: dict | None = None,
) -> dict:
    bucket = bucket or os.environ["PATCHWORK_SITE_BUCKET"]
    distribution = distribution or os.environ.get("PATCHWORK_CF_DISTRIBUTION")
    key_name = key_name or os.environ.get("PATCHWORK_MAPS_KEY_NAME", "patchwork-viewer-maps")
    s3 = boto3.client("s3", region_name=REGION)

    def put(k: str, body: bytes, ctype: str) -> None:
        s3.put_object(Bucket=bucket, Key=k, Body=body, ContentType=ctype)

    html = (ROOT / "viewer" / "index.html").read_text().replace("__MAPS_KEY__", maps_key(key_name))
    put("index.html", html.encode(), "text/html; charset=utf-8")
    if console:  # approval console page, only when the console stack is deployed (enable_console)
        page = (ROOT / "viewer" / "console.html").read_text()
        for k, v in (("__API_URL__", "api_url"), ("__AUTH_DOMAIN__", "auth_domain"), ("__CLIENT_ID__", "client_id")):
            page = page.replace(k, console[v])
        put("console.html", page.encode(), "text/html; charset=utf-8")
    for name in ("corridor.geojson", "segments.geojson", "poi.geojson"):
        put(f"data/{name}", (ROOT / "data" / "corridor" / name).read_bytes(), "application/geo+json")
    gj = (register or Register()).geojson()
    imgs = {p.stem: p for d in (overlay_dirs or []) for p in d.rglob("overlays/*.jpg")}
    n_img = 0
    for f in gj["features"]:
        p = f["properties"]
        img = imgs.get(p.get("overlay_key") or "")
        if img is not None:
            put(f"overlays/{img.name}", img.read_bytes(), "image/jpeg")
            p["overlay_key"] = f"overlays/{img.name}"
            n_img += 1
        elif not (p.get("overlay_key") or "").startswith("overlays/"):
            # keep links to images published by earlier passes
            head = f"overlays/{p.get('overlay_key')}.jpg"
            try:
                s3.head_object(Bucket=bucket, Key=head)
                p["overlay_key"] = head
            except Exception:  # noqa: BLE001 - missing image: no link
                p["overlay_key"] = None
    put("data/defects.geojson", json.dumps(gj).encode(), "application/geo+json")
    meta = {
        "generated": f"{dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC",
        "source": source,
        "defects": len(gj["features"]),
        "overlays": n_img,
    }
    put("data/meta.json", json.dumps(meta).encode(), "application/json")
    if distribution:
        boto3.client("cloudfront").create_invalidation(
            DistributionId=distribution,
            InvalidationBatch={
                "Paths": {"Quantity": 2, "Items": ["/index.html", "/console.html"]},
                "CallerReference": dt.datetime.now(dt.UTC).isoformat(),
            },
        )
    return meta
