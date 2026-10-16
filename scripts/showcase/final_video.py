# ruff: noqa: E501  (slide content and narration are long literal strings)
"""Final submission video (≤ 5 min): narrated by Amazon Polly, captioned, recorded with a real browser.

Every scene: narration text → Polly (neural, en-IN "Kajal") → mp3; the browser records the scene for the length of
its narration (slides, or the LIVE map / console on AWS); ffmpeg joins video + audio per scene, then concatenates.
The console scene signs in with a temporary account (created and deleted by this script) and approves the
priority-1 Hughes Road work order planned by the agent on AgentCore, which files a MOCK ticket.

  uv run --with playwright --with imageio-ffmpeg python scripts/showcase/final_video.py
Output: docs/submission/video/patchwork-demo.mp4 (+ narration.srt)
"""

from __future__ import annotations

import html
import json
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import boto3
import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "submission" / "video"
WORK = OUT / "_work"
URL = "https://d3mt6jrs1ynczo.cloudfront.net"
POOL = "ap-south-1_OIFsAzJwW"
W, H = 1920, 1080
FF = imageio_ffmpeg.get_ffmpeg_exe()
A = ROOT / "docs"

CSS = """
*{box-sizing:border-box} body{margin:0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1d2733}
.s{width:1920px;height:1080px;padding:70px 90px 150px;display:flex;flex-direction:column;position:relative;overflow:hidden}
h1{font-size:64px;margin:0 0 14px;color:#12324f} h2{font-size:52px;margin:0 0 18px;color:#12324f}
.lead{font-size:30px;color:#4a5866;margin:0 0 26px} ul{font-size:32px;line-height:1.45;margin:0;padding-left:34px} li{margin-bottom:10px}
table{border-collapse:collapse;font-size:29px;width:100%} th,td{border-bottom:1px solid #dfe5ec;padding:12px 16px;text-align:left}
th{background:#f1f5f9} .ok{color:#1a7f37;font-weight:700} .no{color:#b42318;font-weight:700}
.big{font-size:84px;font-weight:800;color:#12324f;line-height:1} .k{font-size:26px;color:#4a5866}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:30px} .card{border:2px solid #e3e8ee;border-radius:14px;padding:24px}
.title{background:linear-gradient(135deg,#12324f,#2c6fbb);color:#fff;justify-content:center}
.title h1{color:#fff;font-size:110px} .title .lead{color:#dce8f5;font-size:40px}
img.fit{max-width:100%;max-height:760px;object-fit:contain;border:1px solid #e3e8ee;border-radius:8px;align-self:center}
.term{background:#0f1720;color:#d6e2f0;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:25px;line-height:1.45;
      border-radius:12px;padding:30px 36px;flex:1;white-space:pre-wrap;overflow:hidden}
.term .c{color:#7fd1ff} .term .g{color:#8ee28e} .term .y{color:#ffd479}
"""
CAPTION = """(t) => { let c = document.getElementById('cap');
 if (!c) { c = document.createElement('div'); c.id = 'cap'; c.setAttribute('aria-hidden', 'true');
   c.style.cssText = 'position:fixed;left:0;right:0;bottom:0;padding:18px 60px 22px;background:rgba(18,50,79,.93);' +
     'color:#fff;font:600 27px/1.35 -apple-system,Segoe UI,Roboto,Arial,sans-serif;z-index:99999;text-align:center';
   document.body.appendChild(c); }
 c.textContent = t; }"""


def slide(body: str, cls: str = "") -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='s {cls}'>{body}</div></body></html>"


def img(rel: str) -> str:
    return f"<img class='fit' src='{(A / rel).as_uri()}'>"


def load(name: str) -> dict:
    return json.loads((ROOT / "eval" / "results" / name).read_text())


def scenes() -> list[dict]:
    e2e, rdd, scn = load("end_to_end.json")["passes"], load("rdd_india.json"), load("agent_scenarios.json")
    rec = sum(p["matched"] for p in e2e) / sum(p["truth_visible"] for p in e2e)
    tr = json.loads((A / "submission" / "evidence" / "agentcore-hughes-road.json").read_text())
    calls = [s for s in tr["trace"] if s["type"] == "tool_call"]
    term = "<span class='c'>$ uv run python scripts/aws/invoke_agent.py \"Plan repairs for Hughes Road.\"</span>\n"
    term += "<span class='y'>runtime: Amazon Bedrock AgentCore · model: Amazon Nova Pro · temperature 0</span>\n\n"
    for c in calls:
        arg = json.dumps(c["input"])
        term += f"→ <span class='g'>{c['tool']}</span>  {html.escape(arg[:70])}{'…' if len(arg) > 70 else ''}\n"
    final = re.sub(r"<thinking>.*?</thinking>", "", tr["final"], flags=re.S).strip()
    term += "\n" + html.escape(final.replace("**", "")[:330]) + " …"
    term += f"\n\n<span class='y'>answer check: {len(tr.get('answer_check', {}).get('ungrounded_ids', []))} unknown IDs</span>"
    return [
        dict(
            kind="slide",
            html=slide(
                "<h1>Patchwork</h1><div class='lead'>Measured, verified, human-approved road repair from ordinary dashcam video</div>"
                "<div class='lead' style='margin-top:40px'>Team Googol (PibyThree) · Ganeshan Arumuganainar<br>"
                "OpenCV AI Competition 2026 · Agentic Vision track</div>",
                "title",
            ),
            say="This is Patchwork, by Team Googol, Ganeshan Arumuganainar, for the OpenCV AI Competition twenty "
            "twenty-six, Agentic Vision track. Patchwork turns ordinary dashcam video into a measured register of "
            "road defects, and checks on the next drive whether each repair really happened.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h2>The problem</h2><div class='grid'>"
                "<div class='card'><div class='big'>9,438</div><div class='k'>killed in pothole-related crashes in India, "
                "2020–2024 (Ministry reply to Parliament)</div></div>"
                "<div class='card'><div class='big'>₹400 cr</div><div class='k'>spent by Mumbai's BMC on filling potholes in "
                "2023; 59,000+ potholes recorded</div></div>"
                "<div class='card'><div class='big'>0</div><div class='k'>processes to verify that a repair was done "
                "(Newslaundry, 2026)</div></div></div>"
                "<div class='lead' style='margin-top:40px'>Detection is not the hard part. <b>Measurement</b> and "
                "<b>accountability</b> are.</div>"
            ),
            say="In India, pothole-related crashes killed more than nine thousand four hundred people between twenty "
            "twenty and twenty twenty-four. Mumbai spent four hundred crore rupees filling potholes in twenty "
            "twenty-three, yet there is no process to verify that repairs were done. Detection is not the hard "
            "part. Measurement and accountability are.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h2>Without and with Patchwork</h2><table><tr><th>Today</th><th>With Patchwork</th></tr>"
                "<tr><td>“There is a pothole”</td><td><b>3.39 m² ± 0.07</b>, high severity, 0.44 t of hot-mix</td></tr>"
                "<tr><td>Complaints, duplicates</td><td>Every surveyed metre, one ID per defect, on a map</td></tr>"
                "<tr><td>Loudest complaint first</td><td>Priority from area, severity, schools, hospitals, bus stops</td></tr>"
                "<tr><td>Work orders by hand</td><td>Drafted by the agent from database values only</td></tr>"
                "<tr><td>Filing unchecked</td><td><b>A named engineer approves</b> every order</td></tr>"
                "<tr><td>No proof of repair</td><td><b>Next drive verifies</b>: verified or escalated</td></tr></table>"
            ),
            say="Today an engineer hears: there is a pothole. With Patchwork they get its area in square metres, its "
            "severity and the asphalt it needs, a priority based on nearby schools and hospitals, a drafted work "
            "order that they approve, and proof on the next drive.",
        ),
        dict(
            kind="slide",
            html=slide(f"<h2>Architecture: OpenCV 5 + AWS + agent</h2>{img('submission/architecture.png')}"),
            say="Video uploaded to S3 starts a Step Functions pipeline. AWS Batch on Graviton runs OpenCV five in "
            "parallel containers. Defects go to an Aurora PostGIS register and a public map. An agent on Amazon "
            "Nova, hosted on Bedrock AgentCore, plans the work, and a human approves every order in a signed-in "
            "console.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h2>OpenCV 5 does the measuring</h2><div style='display:flex;gap:30px;flex:1;min-height:0'>"
                f"<div style='flex:2;display:flex'>{img('midpoint/assets/bev_measure.png')}</div>"
                "<div style='flex:1'><ul><li>ChArUco calibration: <b>0.16 px</b></li><li>Homography + one <code>remap</code> "
                "→ 1 cm/px bird's-eye view</li><li>SegFormer-B2 in <b>DNN ENGINE_NEW</b>: matches onnxruntime to "
                "<b>3e-5</b>; ENGINE_CLASSIC cannot load it</li><li>Area with true outlines: <b class='ok'>2.1%</b></li>"
                "<li>Without the bird's-eye view: <b class='no'>46.9%</b></li></ul></div></div>"
            ),
            say="OpenCV five does the measuring. ChArUco calibration, a road-plane homography and one remap give a "
            "one-centimetre bird's-eye view. The segmentation transformer runs in the new DNN engine and matches "
            "onnxruntime; the classic engine cannot load it. With true outlines, area error is two percent. "
            "Without the bird's-eye view, it is forty-seven percent.",
        ),
        dict(
            kind="map",
            say="This is the live map on CloudFront: two hundred and sixty-four defects from two drives over "
            "twenty-eight kilometres of Mumbai roads. The largest, on Hughes Road, measures three point three nine "
            "square metres, high severity, with its evidence image. This one was not seen again on the second "
            "drive, so the register marks it repaired.",
        ),
        dict(
            kind="slide",
            html=slide(f"<h2>The agent, live on Amazon Bedrock AgentCore</h2><div class='term'>{term}</div>"),
            say="Here the agent on AgentCore plans repairs for Hughes Road. It queries the register, checks for existing "
            "work, clusters the defects, estimates materials, drafts work orders and requests approval. Every "
            "number comes from the database, and it cannot file anything itself.",
        ),
        dict(
            kind="console",
            say="The engineer signs in to the approval console, opens the most urgent package, reviews the defects, "
            "the materials and the drafted work order, and approves. Step Functions then files a mock ticket. A "
            "rejection would be recorded as an override.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h2>Closing the loop: did the repair happen?</h2><table><tr><th>After drive 2</th><th>Result</th></tr>"
                "<tr><td>Work orders approved after drive 1</td><td>6</td></tr><tr><td>Verified (defects gone)</td><td>2</td></tr>"
                "<tr><td>Escalated (partly repaired)</td><td>1</td></tr><tr><td>Still open</td><td>3</td></tr>"
                "<tr><td>Verdicts correct against ground truth</td><td class='ok'>8 / 8</td></tr>"
                "<tr><td>Same defect recognised next drive (F1)</td><td>0.80 (target 0.90)</td></tr></table>"
            ),
            say="After the next drive, the agent checks the filed orders. Of six approved packages, two were verified, "
            "one escalated and three are still open, and all eight verdicts were correct against ground truth.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h2>Principal results (held-out survey, 56.8 km)</h2><table><tr><th>Metric</th><th>Result</th><th>Target</th></tr>"
                f"<tr><td>Defects found</td><td class='ok'>{rec:.0%}</td><td>≥ 85%</td></tr>"
                "<tr><td>Area error, full system</td><td class='ok'>13.9%</td><td>≤ 20%</td></tr>"
                "<tr><td>False alarms, clean control road</td><td class='ok'>0.25 / km</td><td>≤ 0.5</td></tr>"
                "<tr><td>Position error (median)</td><td class='ok'>2.6 m</td><td>≤ 8 m</td></tr>"
                "<tr><td>Cost to process</td><td class='ok'>$0.008 / km</td><td>&lt; $0.02</td></tr>"
                f"<tr><td>Agent scenarios / unknown IDs cited</td><td class='ok'>{scn['passed']}/{scn['ran']} · "
                f"{scn['ungrounded_id_answers']}</td><td>0 unknown IDs</td></tr>"
                "<tr><td>Plan changes when only the area changes</td><td class='ok'>priority 3 → 1</td><td>must change</td></tr></table>"
            ),
            say="On a held-out survey of fifty-seven kilometres: ninety-nine percent of defects found, area error under "
            "fourteen percent, a quarter of a false alarm per kilometre on a clean road, and less than one cent per "
            "kilometre to process. In forty scripted agent conversations, thirty-nine pass, and no answer ever "
            "cited a defect that does not exist.",
        ),
        dict(
            kind="slide",
            html=slide(
                f"<h2>Where it fails</h2>{img('submission/failure_gallery.jpg')}"
                f"<div class='lead' style='margin-top:14px'>Real Indian roadside photos (RDD2022-India): "
                f"<b class='no'>{rdd['box_recall']:.0%}</b> of potholes found · look-alikes and fresh patches still flagged</div>"
            ),
            say="We also show where it fails. On real roadside photos from Indian roads, the detector finds only one "
            "percent of potholes, because it learned from close-ups and synthetic roads. Look-alikes and fresh "
            "patches still cause false alarms. Closing this gap needs labelled Indian dashcam frames.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h2>Responsible operation</h2><ul><li>Faces and plates blurred <b>before</b> anything is stored</li>"
                "<li>A named human approves every order; overrides counted on the dashboard</li>"
                "<li>The agent can only cite real defects: tools, database trigger and answer check</li>"
                "<li>Filing is a mock; depth never guessed; simulated data labelled</li>"
                "<li>Terraform, least-privilege roles with a boundary, Cognito, alarms, dashboards, budget guard, CI</li>"
                "<li>Accessibility: 0 axe-core violations on the map and console</li></ul>"
            ),
            say="Faces and plates are blurred before storage. A human approves every order, the agent can only cite "
            "real defects, and filing is mocked. The whole stack is in Terraform, with least-privilege roles, "
            "alarms, dashboards, a budget guard and continuous integration.",
        ),
        dict(
            kind="slide",
            html=slide(
                "<h1>Patchwork</h1><div class='lead'>Measured · verified · human-approved road repair</div>"
                "<div class='lead' style='font-size:30px'>github.com/intragalactic-stranger/OpenCV-Competition-Patchwork-Googol"
                "<br>Live map: d3mt6jrs1ynczo.cloudfront.net · Team Googol · Ganeshan Arumuganainar</div>",
                "title",
            ),
            say="Patchwork: measured, verified, human-approved road repair. The code, the technical report and the live "
            "demo are linked below. Thank you.",
        ),
    ]


def duration(path: Path) -> float:
    err = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def cap(page: Page, text: str) -> None:
    page.evaluate(CAPTION, text)


def run_map(page: Page, secs: float, text: str) -> None:
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(3000)
    cap(page, text)
    page.wait_for_timeout(int(secs * 0.3 * 1000))
    page.locator("#list .row").first.click()
    page.wait_for_timeout(int(secs * 0.4 * 1000))
    page.evaluate("() => document.querySelectorAll('.maplibregl-popup').forEach(p => p.remove())")
    page.locator("#list .row", has_text="repaired").first.click()  # a defect not seen again on drive 2
    page.wait_for_timeout(int(secs * 0.35 * 1000))


def run_console(page: Page, secs: float, text: str, user: str, pw: str) -> None:
    page.goto(URL + "/console.html", wait_until="networkidle")
    page.wait_for_timeout(1500)
    vis = lambda sel: page.locator(sel).locator("visible=true").first  # noqa: E731
    vis("input[name=username]").type(user, delay=60)
    vis("input[name=password]").type(pw, delay=30)
    vis("input[type=submit], button[type=submit]").click()
    page.wait_for_selector(".row", timeout=60000)
    cap(page, text)
    page.wait_for_timeout(2500)
    page.locator(".row").first.click()
    page.wait_for_timeout(int(secs * 0.3 * 1000))
    if page.locator("#approve").count():
        page.locator("#note").type("Video demo: approved after review of area, materials and location.", delay=25)
        page.locator("#approve").click()
        page.wait_for_function("() => (document.getElementById('msg')||{}).textContent?.startsWith('Approved')", timeout=60000)
        page.wait_for_timeout(int(secs * 0.25 * 1000))
    else:
        page.wait_for_timeout(int(secs * 0.3 * 1000))


def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    polly = boto3.client("polly", region_name="ap-south-1")
    sc = scenes()
    for i, s in enumerate(sc):
        mp3 = WORK / f"s{i:02d}.mp3"
        r = polly.synthesize_speech(
            Engine="neural", VoiceId="Kajal", OutputFormat="mp3", Text=s["say"], SampleRate="24000"
        )
        mp3.write_bytes(r["AudioStream"].read())
        s["secs"] = duration(mp3) + 0.8
    total = sum(s["secs"] for s in sc)
    print(f"{len(sc)} scenes, narration {total:.0f} s", flush=True)

    cog = boto3.client("cognito-idp", region_name="ap-south-1")
    user, pw = "video-demo", "Vd" + secrets.token_hex(8) + "9Q"
    cog.admin_create_user(UserPoolId=POOL, Username=user, TemporaryPassword=pw, MessageAction="SUPPRESS")
    cog.admin_set_user_password(UserPoolId=POOL, Username=user, Password=pw, Permanent=True)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
            for i, s in enumerate(sc):
                vd = WORK / f"v{i:02d}"
                ctx = b.new_context(
                    viewport={"width": W, "height": H},
                    record_video_dir=str(vd),
                    record_video_size={"width": W, "height": H},
                )
                page = ctx.new_page()
                if s["kind"] == "slide":
                    f = WORK / f"s{i:02d}.html"
                    f.write_text(s["html"])
                    page.goto(f.as_uri(), wait_until="load")
                    cap(page, s["say"])
                    page.wait_for_timeout(int(s["secs"] * 1000))
                elif s["kind"] == "map":
                    run_map(page, s["secs"], s["say"])
                else:
                    run_console(page, s["secs"], s["say"], user, pw)
                page.close()
                ctx.close()
                print(f"scene {i} recorded", flush=True)
            b.close()
    finally:
        cog.admin_delete_user(UserPoolId=POOL, Username=user)

    parts = []
    for i, s in enumerate(sc):
        webm = next((WORK / f"v{i:02d}").glob("*.webm"))
        mp4 = WORK / f"p{i:02d}.mp4"
        # keep the END of each recording (page loads and sign-in happen first), the length of the narration
        vlen = duration(webm)
        start = max(vlen - s["secs"], 0) if s["kind"] != "slide" else 0.3
        subprocess.run(
            [
                FF,
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{start:.2f}",
                "-i",
                str(webm),
                "-i",
                str(WORK / f"s{i:02d}.mp3"),
                "-t",
                f"{s['secs']:.2f}",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-vf",
                "fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-af",
                "apad",
                str(mp4),
            ],
            check=True,
        )
        parts.append(mp4)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    final = OUT / "patchwork-demo.mp4"
    subprocess.run(
        [
            FF,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(final),
        ],
        check=True,
    )
    t, srt = 0.0, []
    for i, s in enumerate(sc):
        a, z = t, t + s["secs"]
        f = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(x * 1000 % 1000):03d}"  # noqa: E731
        srt.append(f"{i + 1}\n{f(a)} --> {f(z)}\n{s['say']}\n")
        t = z
    (OUT / "narration.srt").write_text("\n".join(srt))
    print(f"wrote {final} ({duration(final):.0f} s)")


if __name__ == "__main__":
    main()
