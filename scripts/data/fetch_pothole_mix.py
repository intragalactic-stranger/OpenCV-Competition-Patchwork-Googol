"""Fetch Pothole Mix v2 (4,340 image/mask pairs, potholes + cracks) from Mendeley Data and verify sha256.

Source : https://data.mendeley.com/datasets/kfth5g2xk3/2 (Ranieri, Moscoso Thompson, Biasotti; SHREC'22)
Licence: CC BY-NC 3.0. Models trained on it are research / non-commercial (decision D-24); the
         licence-clean model is trained on synthetic data only.
Usage  : uv run python scripts/data/fetch_pothole_mix.py [--keep-zip]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import urllib.request
import zipfile
from pathlib import Path

URL = (
    "https://data.mendeley.com/public-files/datasets/kfth5g2xk3/files/"
    "d5b8a18b-b1fa-4637-88ad-56263431ef4e/file_downloaded"
)
SHA256 = "7b95ff42fcd00db1136bb6e1f8b81a9d436e489409655cdfff698fd5b988d74e"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "pothole_mix"
UA = {"User-Agent": "Patchwork/0.1 (OpenCV AI Competition 2026 research project)"}


def download(dst: Path) -> None:
    h = hashlib.sha256()
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while chunk := r.read(8 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if done % (256 << 20) < (8 << 20):
                print(f"{done / 1e9:.2f} / {total / 1e9:.2f} GB", flush=True)
    if h.hexdigest() != SHA256:
        dst.unlink()
        raise SystemExit(f"sha256 mismatch: {h.hexdigest()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-zip", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    z = OUT / "pothole-mix-v1.0-20220526.zip"
    if not z.exists():
        download(z)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(OUT)
    if not args.keep_zip:
        z.unlink()
    (OUT / "SOURCE.md").write_text(
        f"# Pothole Mix v2\n\n- URL: https://data.mendeley.com/datasets/kfth5g2xk3/2\n- sha256 (zip): {SHA256}\n"
        f"- Licence: CC BY-NC 3.0 (non-commercial; models trained on it inherit the restriction)\n"
        f"- Fetched: {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC\n"
    )
    print(f"extracted to {OUT}")


if __name__ == "__main__":
    main()
