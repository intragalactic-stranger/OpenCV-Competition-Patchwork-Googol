"""Screenshot of the live map viewer (headless Chromium via Playwright) for the midpoint pack.

uv run --with playwright python scripts/figures/viewer_screenshot.py [--url URL] [--click-largest]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://d3mt6jrs1ynczo.cloudfront.net")
    ap.add_argument("--click-largest", action="store_true", help="open the popup of the largest defect")
    ap.add_argument("--out", type=Path, default=ROOT / "main_docs" / "midpoint" / "assets" / "viewer.png")
    args = ap.parse_args()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        page = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        page.goto(args.url, wait_until="networkidle")
        page.wait_for_timeout(6000)
        if args.click_largest:
            rows = page.locator("#list .row")
            if rows.count():
                rows.first.click()
                page.wait_for_timeout(5000)
        page.screenshot(path=str(args.out))
        b.close()
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
