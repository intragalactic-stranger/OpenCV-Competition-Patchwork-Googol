# ruff: noqa: E501  (slide text and CSS)
"""Build the reviewer showcase: slides (PNG + one PDF), live-viewer screenshots and a captioned screen recording.

  uv run --with playwright --with imageio-ffmpeg python scripts/showcase/build.py [--no-video]

Output: main_docs/midpoint/showcase/
  Patchwork-midpoint-slides.pdf     the deck (one page per slide)
  Patchwork-midpoint-demo.mp4       screen recording: live map in use, then the slides (git-ignored, large)
  screenshots/NN-*.png              every slide and every map view as a picture
Every number on the slides is copied from the generated docs (04, 07, 08, 02); nothing is typed from memory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "main_docs" / "midpoint" / "showcase"
SHOTS = OUT / "screenshots"
URL = "https://d3mt6jrs1ynczo.cloudfront.net"
W, H = 1600, 900

CSS = """
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1d2733; background: #fff; }
.slide { width: 1600px; height: 900px; padding: 56px 72px 40px; position: relative; overflow: hidden;
         page-break-after: always; break-after: page; display: flex; flex-direction: column; }
.slide h1 { font-size: 44px; margin: 0 0 10px; }
.slide h2 { font-size: 38px; margin: 0 0 6px; color: #12324f; }
.slide .lead { font-size: 22px; color: #4a5866; margin: 0 0 22px; }
.slide .foot { position: absolute; bottom: 16px; left: 72px; right: 72px; font-size: 14px; color: #8a96a3;
               display: flex; justify-content: space-between; border-top: 1px solid #e3e8ee; padding-top: 8px; }
.cols { display: flex; gap: 40px; flex: 1; min-height: 0; }
.cols > div { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.img { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; }
.img img { max-width: 100%; max-height: 100%; object-fit: contain; border: 1px solid #e3e8ee; border-radius: 6px; }
ul { font-size: 23px; line-height: 1.5; margin: 0; padding-left: 26px; }
li { margin-bottom: 8px; }
table { border-collapse: collapse; font-size: 22px; width: 100%; }
th, td { border-bottom: 1px solid #e3e8ee; padding: 9px 12px; text-align: left; }
th { background: #f3f6f9; }
.ok { color: #1e8a4c; font-weight: 700; } .no { color: #c0392b; font-weight: 700; } .na { color: #8a6d00; font-weight: 700; }
.big { font-size: 64px; font-weight: 800; color: #12324f; } .tag { display: inline-block; background: #eef4fb; color: #12324f;
       border-radius: 6px; padding: 4px 10px; font-size: 18px; margin: 0 8px 8px 0; }
.title { justify-content: center; background: linear-gradient(135deg, #12324f, #2c6fbb); color: #fff; }
.title h1 { font-size: 72px; color: #fff; } .title .lead { color: #dce8f5; font-size: 28px; }
.flow { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-size: 19px; margin-bottom: 18px; }
.flow span.b { background: #eef4fb; border: 1px solid #c9dbee; border-radius: 6px; padding: 8px 12px; }
.flow span.a { color: #8a96a3; }
.note { font-size: 18px; color: #4a5866; margin-top: 10px; }
"""


def slide(title: str, lead: str, body: str, n: int, total: int, cls: str = "") -> str:
    return (
        f'<section class="slide {cls}"><h2>{title}</h2><p class="lead">{lead}</p>{body}'
        f'<div class="foot"><span>Patchwork · OpenCV AI Competition 2026 · midpoint checkpoint</span>'
        f"<span>{n} / {total}</span></div></section>"
    )


def img(name: str) -> str:
    return f'<div class="img"><img src="../assets/{name}"></div>'


def build_slides() -> tuple[str, list[str]]:
    e2e = json.loads((ROOT / "eval/results/end_to_end.json").read_text())["passes"]
    km = sum(p["km"] for p in e2e)
    names, parts = [], []
    S = [
        (
            "title",
            "",
            "",
            '<div style="margin:auto 0"><h1>Patchwork</h1><p class="lead">A road-defect register from ordinary dashcam '
            "video: damage measured in <b>m²</b> with <b>OpenCV 5</b>, tracked pass after pass, turned into repair work "
            "by an <b>AI agent</b> that cannot act without human approval.</p>"
            '<p class="lead">Mumbai · AWS ap-south-1 · OpenCV AI Competition 2026, Agentic Vision · '
            "Midpoint checkpoint · 14 October 2026</p></div>",
            "title",
        ),
        (
            "problem",
            "What a ward engineer needs, and what we built",
            "Detecting a pothole is solved. Knowing <b>how big</b>, <b>where exactly</b>, and <b>whether it was really "
            "repaired</b> is not.",
            '<div class="cols"><div><ul><li><b>Measure</b>: dashcam frame → calibrated top-down view at 1 cm/pixel → '
            "damaged area in m² ± uncertainty</li><li><b>Locate</b>: on a named road, by chainage, also in the 3.1 km "
            "tunnel</li><li><b>Track</b>: the same defect across passes → new / unchanged / degraded / repaired</li>"
            "<li><b>Act</b>: an Amazon Nova agent groups defects into work packages, estimates hot-mix, ranks by nearby "
            "schools and hospitals, and <b>requests human approval</b></li></ul>"
            '<p class="note">28.6 km real Mumbai loop: Marine Drive, Coastal Road, Worli Seaface, Haji Ali '
            "(OpenStreetMap geometry, 84 schools / hospitals / bus stops).</p></div>"
            f"<div>{img('corridor_map.png')}</div></div>",
        ),
        (
            "data",
            "Exact ground truth: a simulated dashcam over the real road network",
            "Every pothole's true area, position and repair status is known exactly, so every number below is graded "
            "against truth, not against a tape measure.",
            '<div class="cols"><div style="flex:2">' + img("synth_contact_sheet.jpg") + "</div><div><ul>"
            "<li>2 worlds × 3 passes × 28.6 km rendered on AWS Batch</li><li>Seed 07 for training, <b>seed 11 held "
            "out</b> for every result</li><li>Traps on purpose: shadows, wet patches, manholes, seams, old repairs</li>"
            "<li>Real photos for the model: Pothole Mix (4,340 masked images)</li><li>The viewer states clearly that "
            "the defects are simulated</li></ul></div></div>",
        ),
        (
            "geometry",
            "OpenCV 5 geometry: from pixels to square metres",
            "ChArUco calibration (RMS 0.164 px) → per-frame road pitch from lane lines → bird's-eye view at 1 cm/px "
            "→ area is a pixel count.",
            f'<div class="cols"><div>{img("calibration.png")}</div><div>{img("bev_measure.png")}</div></div>'
            '<p class="note"><b>2.1% area error with perfect outlines</b> (target ≤ 5%): the geometry is not the '
            "bottleneck. Frame triage keeps 284 frames/km and loses no defects; faces and plates are blurred before "
            "storage; median position error 2.6 m (raw GNSS 6.2 m).</p>",
        ),
        (
            "model",
            "The model: SegFormer-B0 running in OpenCV 5's new DNN engine",
            "Trained on CPU only (AWS Graviton Spot). Runs in <code>ENGINE_NEW</code>, identical to onnxruntime "
            "(max difference 2.0e-5, target 1e-3). The classic 4.x-style engine cannot load it at all.",
            img("seg_examples.jpg")
            + '<p class="note">Top: real photos (held-out test split). Bottom: synthetic dashcam strips (held-out '
            "road stretch). Green = truth, red = model. Worst cases shown on purpose. IoU 0.50 real / 0.57 synthetic."
            "</p>",
        ),
        (
            "finetune",
            "Fine-tune with look-alikes: teaching the model what is <i>not</i> damage",
            "1,788 frames of shadows, wet patches, manholes, seams and old repairs labelled “not damage”; "
            "seg-v2 → seg-v3 (2.7 h CPU, survived 3 Spot interruptions by resuming from S3 checkpoints).",
            img("hard_neg_compare.jpg")
            + '<table style="margin-top:14px"><tr><th>Held-out set</th><th>False-alarm images, seg-v2</th>'
            "<th>seg-v3</th></tr><tr><td>Look-alikes only, no damage (480)</td><td>86</td><td><b>41</b></td></tr>"
            "<tr><td>Real photos, test (318 without damage)</td><td>73</td><td><b>54</b></td></tr>"
            "<tr><td>Synthetic Mumbai, val (719 without damage)</td><td>64</td><td><b>23</b></td></tr></table>",
        ),
        (
            "pipeline",
            "The cloud pipeline: uploading a survey is the trigger",
            f"Held-out survey: 2 passes, {km:.1f} km. One 28.4 km pass in 15–17 min wall-clock; perception compute "
            "$0.0021 per km (target < $0.02).",
            '<div class="flow"><span class="b">S3 upload</span><span class="a">→</span><span class="b">EventBridge'
            '</span><span class="a">→</span><span class="b">Step Functions</span><span class="a">→</span>'
            '<span class="b">AWS Batch, Graviton Spot, 10 clips in parallel (OpenCV 5)</span><span class="a">→</span>'
            '<span class="b">Aurora PostgreSQL + PostGIS register</span><span class="a">→</span>'
            '<span class="b">CloudFront map</span><span class="a">→</span><span class="b">Nova agent + approval '
            "gate</span></div>" + img("sfn_run.png"),
        ),
        (
            "viewer",
            "Live map: every defect in m², with its evidence",
            f"{URL} · click a dot: area ± uncertainty, severity, status across passes, hot-mix estimate, and the "
            "dashcam view next to the measured top-down view.",
            img("viewer.png"),
        ),
        (
            "results",
            "Results on the held-out survey (56.8 km, exact ground truth)",
            "Same survey, same pipeline, before and after the look-alike fine-tune.",
            "<table><tr><th>Metric</th><th>seg-v2</th><th>seg-v3</th><th>Target</th><th></th></tr>"
            '<tr><td>Recall (visible defects found)</td><td>0.95</td><td><b>0.94</b></td><td>≥ 0.85</td><td class="ok">'
            "met</td></tr>"
            "<tr><td>False alarms per km, clean control section</td><td>3.87</td><td><b>0.30</b></td><td>≤ 0.5</td>"
            '<td class="ok">met</td></tr>'
            "<tr><td>False alarms per km, whole survey</td><td>10.05</td><td><b>3.1</b></td><td>–</td><td></td></tr>"
            "<tr><td>Area error (MAPE), end to end</td><td>33.7%</td><td><b>27.8%</b></td><td>≤ 20%</td>"
            '<td class="no">not yet</td></tr>'
            "<tr><td>Area error, geometry only (perfect outlines)</td><td colspan=2>2.1% (geometry, same for both)</td><td>≤ 5%</td>"
            '<td class="ok">met</td></tr>'
            "<tr><td>Re-identification across passes (F1)</td><td>0.57</td><td><b>0.73</b></td><td>≥ 0.90 (final)</td>"
            '<td class="na">second half</td></tr>'
            '<tr><td>Median position error</td><td colspan=2>2.6 m (localisation, same for both)</td><td>≤ 8 m</td><td class="ok">met</td></tr>'
            "<tr><td>OpenCV 5 ENGINE_NEW vs onnxruntime</td><td>2.4e-5</td><td><b>2.0e-5</b></td><td>≤ 1e-3</td>"
            '<td class="ok">met</td></tr>'
            "<tr><td>Perception cost per km</td><td>$0.0019</td><td><b>$0.0021</b></td><td>&lt; $0.02</td>"
            '<td class="ok">met</td></tr></table>'
            '<p class="note">Generated by <code>make eval-midpoint</code> from <code>eval/results/*.json</code> '
            "(04-RESULTS §1, §3).</p>",
        ),
        (
            "area",
            "Measured vs true area, every matched defect",
            "Small and medium potholes sit near the diagonal (median error 18%). Large shallow depressions are still "
            "under-measured: the model marks only part of their soft edge.",
            img("area_scatter.png"),
        ),
        (
            "ab",
            "Proof that vision drives the agent: run A vs run B",
            "Same pothole (Marine Drive, chainage 3193 m), same prompt, same model (Amazon Nova Pro, temperature 0). "
            "Only the measured area differs.",
            "<table><tr><th></th><th>Run A (as measured by the pipeline)</th><th>Run B (area swapped)</th></tr>"
            "<tr><td>Measured area</td><td>0.35 m² (true 0.35 m²)</td><td>3.10 m²</td></tr>"
            "<tr><td>Priority (1 = urgent)</td><td>2</td><td><b>1</b></td></tr>"
            "<tr><td>Exposure score</td><td>5.86</td><td>21.70</td></tr>"
            "<tr><td>Hot-mix needed</td><td>0.046 t</td><td><b>0.401 t</b></td></tr>"
            "<tr><td>Tool calls</td><td colspan=2>query_defects → cluster_into_packages → estimate_materials → "
            "draft_work_order → request_human_approval</td></tr></table>"
            '<p class="note">Priority and quantities are computed by tools from the register, so the change is caused '
            "by the measurement, not by model randomness. Unknown defect IDs are rejected by the tool and by a "
            "database trigger.</p>"
            '<div class="cols" style="margin-top:18px"><div><p class="lead" style="margin:0 0 6px"><b>Agent, run A:</b></p>'
            '<p class="note" style="font-size:20px">“…medium severity, an area of 0.3531 m², and is located near two '
            "hospitals… The estimated materials required are 0.0177 m³ of hot-mix asphalt.”</p></div>"
            '<div><p class="lead" style="margin:0 0 6px"><b>Agent, run B:</b></p><p class="note" style="font-size:20px">'
            "“…It has a priority of 1 due to its high severity, an area of 3.1 m², and its proximity to two hospitals. "
            "The estimated materials for this package are 0.155 m³ of hot-mix asphalt…”</p></div></div>"
            '<p class="note">Full traces: eval/results/agent/ablation-A-400AET.json, ablation-B-400AET.json</p>',
        ),
        (
            "gate",
            "The human gate: the agent can only ask",
            "A Step Functions workflow holds the approval token in the database; the agent never sees it.",
            '<div class="flow"><span class="b">Agent drafts work order</span><span class="a">→</span>'
            '<span class="b">request_human_approval</span><span class="a">→</span><span class="b">Step Functions waits '
            '(task token, 7 days)</span><span class="a">→</span><span class="b">Engineer: approve / reject</span>'
            '<span class="a">→</span><span class="b">filed: MOCK ticket · or · rejected: override recorded</span></div>'
            '<div class="cols"><div><ul><li>Road-wide request “Plan repairs for Khan Abdul Gaffar Khan Marg” → '
            "<b>24 work packages</b> in 78 s (84 k Nova Pro tokens ≈ $0.10)</li>"
            "<li><b>Approved</b> (priority 1, 3.40 m²) → state <code>filed</code>, ticket "
            "<code>MOCK-aea1bb9b…</code>: nothing is sent to a real authority</li>"
            "<li><b>Rejected</b> (0.02 m², “re-inspect first”) → state <code>rejected</code>, recorded as an override"
            "</li><li>No answer → the request expires after 7 days</li></ul>"
            '<p class="note">Honest note: the agent\'s final text summary listed one package twice. The packages, '
            "numbers and approvals in the database were correct, because code computes them, not the model's prose."
            "</p></div></div>",
        ),
        (
            "cost",
            "What the credits bought: first half",
            "Every AWS service, step by step, is in 08-SERVICE-MAPPINGS. Billed from AWS Cost Explorer.",
            '<div class="cols"><div><p class="big">$0.00</p><p class="lead">real money paid; everything on '
            "promotional credits, guarded by a $0.01 budget alarm</p><ul><li>$9.23 billed so far (≈ $10.6 once Spot "
            "billing catches up)</li><li>Perception: <b>$0.0021 per km</b></li><li>Model training on CPU: $1.7 "
            "(seg-v2) + $1.2 (seg-v3)</li><li>13 AWS services, 42 resources, all Terraform</li></ul></div>"
            '<div><table style="font-size:20px"><tr><th>Billed by AWS (2026-10-12 → 13)</th><th>Usage</th></tr>'
            "<tr><td>EC2 compute: dev workstation $4.21 · Batch Spot $2.20</td><td>$6.43</td></tr>"
            "<tr><td>S3 (requests, cross-region transfer)</td><td>$0.86</td></tr>"
            "<tr><td>Aurora Serverless v2 register</td><td>$0.57</td></tr>"
            "<tr><td>Cost Explorer API (this report)</td><td>$0.42</td></tr>"
            "<tr><td>EC2 other (disks), VPC (public IPs)</td><td>$0.62</td></tr>"
            "<tr><td>Bedrock: Amazon Nova Pro (agent)</td><td>$0.33</td></tr>"
            "<tr><td>Secrets, ECR, Location, EventBridge, Step Functions</td><td>$0.01</td></tr>"
            "<tr><td><b>Total, all paid by credits</b></td><td><b>$9.23</b></td></tr></table></div></div>",
        ),
        (
            "next",
            "Second half: what the remaining credits pay for (≈ $370, range $260–470)",
            "The first half proved the pipeline at the cheapest settings. The second half buys accuracy and the full "
            "agent.",
            '<div class="cols"><div><ul><li><b>GPU training</b>: g6.xlarge (NVIDIA L4) via AWS Batch, SegFormer-B2, '
            "≈ 110 GPU-hours → $80</li><li><b>40-scenario agent evaluation</b> on Amazon Nova, run live ≈ 50 times "
            "→ $74; LLM judge + VLM attributes</li><li>Aurora for 8-pass verification and the console → $40</li>"
            "<li>Development workstation → $92</li><li>AgentCore, Lambda, API Gateway, Cognito, CloudWatch, S3, "
            "pipeline evaluation runs</li></ul></div><div><ul><li>Fix manhole false alarms, merge split blobs</li>"
            "<li>Area error → 20%: soft-boundary labels, larger model, mask fusion</li><li>Re-ID → 0.90: ORB + "
            "homography matcher over 8 passes</li><li>Full 10-tool agent on AgentCore, web console</li>"
            "<li>Caps on every line; no padded spend</li></ul></div></div>",
        ),
    ]
    total = len(S)
    for i, (key, title, lead, body, *cls) in enumerate(S, 1):
        names.append(key)
        if key == "title":
            parts.append(f'<section class="slide title">{body}</section>')
        else:
            parts.append(slide(title, lead, body, i, total, *(cls or [""])))
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    return html, names


CAPTION_JS = """(t) => {
  let c = document.getElementById('__cap');
  if (!c) { c = document.createElement('div'); c.id = '__cap';
    c.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;background:rgba(18,50,79,.92);color:#fff;' +
      'font:600 24px -apple-system,Segoe UI,Roboto,sans-serif;padding:14px 28px;line-height:1.35';
    document.body.appendChild(c); }
  c.textContent = t; c.style.display = t ? 'block' : 'none';
}"""


def cap(page: Page, text: str) -> None:
    page.evaluate(CAPTION_JS, text)


def click_feature(page: Page, pick_js: str, zoom: float = 17.5) -> dict:
    """Fly to a defect chosen in the page and click its dot like a user would."""
    f = page.evaluate(
        f"""async () => {{
      const d = await fetch('data/defects.geojson', {{cache: 'no-store'}}).then(r => r.json());
      const f = ({pick_js})(d.features);
      map.flyTo({{center: f.geometry.coordinates, zoom: {zoom}, duration: 2500}});
      return f;
    }}"""
    )
    page.wait_for_timeout(3500)
    xy = page.evaluate("(c) => { const p = map.project(c); return [p.x, p.y]; }", f["geometry"]["coordinates"])
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + xy[0], box["y"] + xy[1], steps=15)
    page.mouse.click(box["x"] + xy[0], box["y"] + xy[1])
    page.wait_for_timeout(1500)
    return f["properties"]


def close_popups(page: Page) -> None:
    page.evaluate("() => document.querySelectorAll('.maplibregl-popup').forEach(p => p.remove())")


MIDPOINT_CAPTIONS = {
    "overview": "Live map on AWS CloudFront: the defect register built from the held-out survey (2 passes, 56.8 km)",
    "control": "Purple: the Coastal Road control section (clean surface) used to count false alarms: 0.30 per km",
}


def map_tour(page: Page, shots: bool, hold: float = 1.0, captions: dict | None = None) -> None:
    c = {**MIDPOINT_CAPTIONS, **(captions or {})}
    ms = lambda s: int(s * 1000 * hold)  # noqa: E731
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(6000)
    cap(page, c["overview"])
    page.wait_for_timeout(ms(5))
    if shots:
        page.screenshot(path=str(SHOTS / "map-01-overview.png"))
    cap(page, "Left: totals from the register. Dots: every defect, coloured by severity, sized by measured m²")
    page.wait_for_timeout(ms(4))
    cap(page, "Largest defect: area ± uncertainty, status across passes, hot-mix estimate, and the evidence image")
    page.locator("#list .row").first.click()
    page.wait_for_timeout(ms(7))
    if shots:
        page.screenshot(path=str(SHOTS / "map-02-largest-defect.png"))
    close_popups(page)
    cap(page, "A defect seen on both passes and judged 'unchanged' (the register links passes automatically)")
    click_feature(
        page,
        "(fs) => fs.filter(f => f.properties.status === 'unchanged' && f.properties.overlay_key)"
        ".sort((a, b) => b.properties.latest_area_m2 - a.properties.latest_area_m2)[3]",
    )
    page.wait_for_timeout(ms(6))
    if shots:
        page.screenshot(path=str(SHOTS / "map-03-unchanged-across-passes.png"))
    close_popups(page)
    cap(page, "A defect that grew between passes: status 'degraded'")
    click_feature(
        page,
        "(fs) => fs.filter(f => f.properties.status === 'degraded' && f.properties.overlay_key)"
        ".sort((a, b) => b.properties.latest_area_m2 - a.properties.latest_area_m2)[0]",
    )
    page.wait_for_timeout(ms(6))
    if shots:
        page.screenshot(path=str(SHOTS / "map-04-degraded.png"))
    close_popups(page)
    cap(page, c["control"])
    page.evaluate(
        """async () => {
      const s = await fetch('data/segments.geojson', {cache: 'no-store'}).then(r => r.json());
      const pts = s.features.filter(f => f.properties.is_control).flatMap(f =>
        f.geometry.type === 'LineString' ? f.geometry.coordinates : f.geometry.coordinates.flat());
      const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
      map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]],
                    {padding: {top: 60, bottom: 120, left: 60, right: 60}, duration: 2500});
    }"""
    )
    page.wait_for_timeout(ms(6))
    if shots:
        page.screenshot(path=str(SHOTS / "map-05-control-section.png"))
    cap(page, "")


def slides_tour(page: Page, n: int, secs: list[float]) -> None:
    page.goto((OUT / "slides.html").as_uri(), wait_until="load")
    page.wait_for_timeout(800)
    for i in range(n):
        page.evaluate("(i) => document.querySelectorAll('.slide')[i].scrollIntoView()", i)
        page.wait_for_timeout(int(secs[i] * 1000))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--final-map", type=Path, default=None, help="only screenshot the live map into this folder")
    ap.add_argument("--control-fp", default="", help="final control-section false alarms per km, for the caption")
    args = ap.parse_args()
    if args.final_map:  # final register: map screenshots only (the midpoint slides and video stay as they were)
        global SHOTS
        SHOTS = args.final_map
        SHOTS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
            page = b.new_page(viewport={"width": W, "height": H})
            map_tour(
                page,
                shots=True,
                hold=0.4,
                captions={
                    "overview": "Live map on AWS CloudFront: final register (seg-v4), held-out survey, 2 passes, 56.8 km",
                    "control": f"Purple: the Coastal Road control section (clean surface): {args.control_fp} false alarms per km",
                },
            )
            b.close()
        print(f"map screenshots -> {SHOTS}")
        return
    SHOTS.mkdir(parents=True, exist_ok=True)
    html, names = build_slides()
    (OUT / "slides.html").write_text(html)
    launch = {"args": ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"]}
    with sync_playwright() as p:
        b = p.chromium.launch(**launch)
        page = b.new_page(viewport={"width": W, "height": H})
        page.goto((OUT / "slides.html").as_uri(), wait_until="load")
        page.wait_for_timeout(1000)
        for i, name in enumerate(names):
            page.locator(".slide").nth(i).screenshot(path=str(SHOTS / f"slide-{i + 1:02d}-{name}.png"))
        page.pdf(
            path=str(OUT / "Patchwork-midpoint-slides.pdf"), width=f"{W}px", height=f"{H}px", print_background=True
        )
        map_tour(page, shots=True, hold=0.4)
        b.close()
        print(f"slides + screenshots -> {OUT.relative_to(ROOT)}")
        if args.no_video:
            return
        vid_dir = OUT / "_video"
        shutil.rmtree(vid_dir, ignore_errors=True)
        b = p.chromium.launch(**launch)
        ctx = b.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(vid_dir),
            record_video_size={"width": W, "height": H},
        )
        page = ctx.new_page()
        map_tour(page, shots=False)
        secs = [6 if k == "title" else 11 if k in ("results", "ab", "gate", "next", "pipeline") else 8 for k in names]
        slides_tour(page, len(names), secs)
        page.close()
        ctx.close()
        b.close()
    webm = next(vid_dir.glob("*.webm"))
    import imageio_ffmpeg

    mp4 = OUT / "Patchwork-midpoint-demo.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(webm),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    shutil.rmtree(vid_dir)
    print(f"video -> {mp4.relative_to(ROOT)} ({mp4.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
