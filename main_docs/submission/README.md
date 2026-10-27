# Patchwork: competition submission pack

**OpenCV AI Competition 2026 · Agentic Vision track · Team Googol (PibyThree) · Ganeshan Arumuganainar**

| Required | Where |
|---|---|
| Technical report (problem, users, architecture, OpenCV 5, AWS, evaluation, limitations, responsible use) | [TECHNICAL-REPORT.md](TECHNICAL-REPORT.md) · PDF: [Patchwork-Technical-Report.pdf](Patchwork-Technical-Report.pdf) |
| Judge-accessible code repository | https://github.com/intragalactic-stranger/OpenCV-Competition-Patchwork-Googol (public, Apache-2.0, release [v1.0](https://github.com/intragalactic-stranger/OpenCV-Competition-Patchwork-Googol/releases/tag/v1.0)) |
| Pinned dependencies + build, deployment and test instructions | [BUILD-DEPLOY-TEST.md](BUILD-DEPLOY-TEST.md) · `uv.lock`, [`requirements.lock.txt`](../../requirements.lock.txt), Terraform lock file, exact container tags · `make setup / check / smoke / images / deploy / teardown` |
| Architecture diagram (OpenCV 5, AWS, agent) | [architecture.png](architecture.png) (source: [architecture.html](architecture.html)) · agent workflow: [agent-workflow.png](agent-workflow.png) |
| Working web endpoint | Map (public): https://d3mt6jrs1ynczo.cloudfront.net · Approval console (sign-in): https://d3mt6jrs1ynczo.cloudfront.net/console.html, judge login supplied privately with the submission form · Agent on Bedrock AgentCore: `scripts/aws/invoke_agent.py` |
| Video, under 5 minutes (team, application working, architecture, principal results) | https://youtu.be/VupHYPRwLks · mirror https://d3mt6jrs1ynczo.cloudfront.net/video/patchwork-demo.mp4 (3 min 41 s, narrated, captioned; also attached to release v1.0; captions: [narration.srt](video/narration.srt)) |
| Evaluation evidence with failure cases and limitations | Report §7 · generated table in [FINAL-REPORT.md](../FINAL-REPORT.md) · [failure_gallery.jpg](failure_gallery.jpg) · result files in `eval/results/` |

## Agentic Vision Award → evidence

| Required | Where |
|---|---|
| Agent workflow diagram (perception, decision/orchestration, action) | [agent-workflow.png](agent-workflow.png) · report §12 |
| Trace showing OpenCV 5 output changes a later decision, tool call or action | Run A/B: 0.20 → 3.10 m² changes priority 3 → 1 and hot-mix 0.025 → 0.401 t; traces `eval/results/agent/ablation-*-6DZ5GM.json`; report §12 |
| Task success, failure handling, observability, human control | Report §12 table: 39/40 scenarios, 12/12 adversarial, 0 ungrounded IDs, 8/8 repair verdicts; operations dashboard with override rate; approval gate |

The Best Use of COOL Award is not claimed: Patchwork uses the standard OpenCV 5.0.0 build on Graviton, not COOL.

## Judging criteria → evidence

| Criterion (weight) | What to look at |
|---|---|
| **Technical execution (30%)**: correctness and depth of OpenCV 5 | Report §4: every OpenCV 5 function by stage, with its measured result. ChArUco calibration 0.16 px · one-`remap` bird's-eye view · area 2.1% with true outlines vs **46.9% without rectification** · SegFormer-B2 in **DNN `ENGINE_NEW`** (3.2e-5 vs onnxruntime; `ENGINE_CLASSIC` cannot load it) · optical-flow triage (0% defects lost) · YuNet privacy · end to end recall 0.99, area error 13.9% |
| **Innovation (20%)** | Measured m², not just detection · repair verification across drives (matcher on camera-derived lateral offset + pass closing) · run A/B proving the vision drives the agent's plan · synthetic survey on real city geometry with exact truth · three-layer grounding (tools, DB trigger, answer check) |
| **Real-world impact (20%)** | Report §1–2: 9,438 pothole deaths in India 2020–24; BMC spent ₹400 cr in 2023 with no repair verification · without/with table · honest real-photo result (§7.4) and what it takes to deploy |
| **User experience (10%)** | Live map and approval console · axe-core: **0 violations** on both (map was 3) · keyboard-only flow · phone layout · the console waits for a paused database instead of failing · agent answers cite IDs |
| **Documentation and presentation (10%)** | This pack · 7-page PDF report · 3:41 narrated video · model cards (`main_docs/MODEL-CARD.md`) · decision log D-01…D-40 · root README with quick start verified on a fresh clone |
| **Cloud delivery, reproducibility, responsible operation (10%)** | Whole stack in Terraform; pinned deps; CI on every push · least-privilege IAM with a permissions boundary, Cognito, CloudFront OAC, Secrets Manager · two CloudWatch dashboards (pipeline; operations with **override rate**, agent runs, ungrounded IDs, AgentCore, Nova tokens, console API) + alarms → email · budget guard, ≈ $32 total · privacy blur, human approval, mock filing · `make teardown` |
