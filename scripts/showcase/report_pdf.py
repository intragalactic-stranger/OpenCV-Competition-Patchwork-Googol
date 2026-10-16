# ruff: noqa: E501  (embedded CSS)
"""Technical report → PDF (docs/submission/Patchwork-Technical-Report.pdf), from the Markdown source.

  uv run --with markdown --with playwright python scripts/showcase/report_pdf.py
Relative links become GitHub links so they work from the PDF; images are embedded.
"""

from __future__ import annotations

import re
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "submission" / "TECHNICAL-REPORT.md"
OUT = ROOT / "docs" / "submission" / "Patchwork-Technical-Report.pdf"
GH = "https://github.com/intragalactic-stranger/OpenCV-Competition-Patchwork-Googol/blob/main/docs/submission/"
CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.42; color: #1d2733; }
h1 { font-size: 19pt; color: #12324f; margin: 0 0 6px; line-height: 1.2; }
h2 { font-size: 13.5pt; color: #12324f; border-bottom: 2px solid #12324f; padding-bottom: 3px; margin: 18px 0 8px; page-break-after: avoid; }
h3 { font-size: 11pt; color: #12324f; margin: 12px 0 6px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; } th, td { border: 1px solid #d9e0e7; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #eef2f6; } code { font-size: 8.6pt; background: #f3f5f7; padding: 0 3px; border-radius: 3px; }
img { max-width: 100%; display: block; margin: 8px auto; border: 1px solid #e3e8ee; }
a { color: #0b5cad; text-decoration: none; } hr { border: 0; border-top: 1px solid #d9e0e7; }
"""


def main() -> None:
    md = SRC.read_text()
    md = re.sub(r"\]\((?!https?://)([^)#\s]+\.md)\)", lambda m: f"]({GH}{m.group(1)})", md)
    body = markdown.markdown(md, extensions=["tables", "sane_lists"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    tmp = SRC.parent / "_report.html"
    tmp.write_text(html)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.as_uri(), wait_until="load")
        pg.pdf(
            path=str(OUT),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template="<div style='font-size:7pt;color:#8a96a3;width:100%;text-align:center'>Patchwork · "
            "technical report · <span class='pageNumber'></span>/<span class='totalPages'></span></div>",
            margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
        )
        b.close()
    tmp.unlink()
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
