# Demo guide (midpoint checkpoint)

**Length:** about 10 minutes. **Setup:** browser tabs pre-opened; terminal in the repo; AWS console logged in (ap-south-1).
**Fallback:** a recorded run of the same sequence (`assets/demo_recording.mp4`), because live demos fail on venue Wi-Fi.

## Before the demo (T−30 min)
```bash
make preflight            # checks AWS identity, Aurora awake, Batch CE valid, viewer URL 200, model in S3
make synth-demo           # renders a short 2–3 km Worli Seaface pass (≈ 3 min) if not cached
```
Open tabs: (1) the viewer URL, (2) the Step Functions console on `patchwork-process-clip`, (3) this repo's `docs/midpoint/04-RESULTS-AND-OUTPUTS.md`, (4) `02-COST-REPORT.md`.

## Script

| # | Time | Do | Say (key message) |
|---|---|---|---|
| 1 | 0:00 | Show the proposal's one-liner and the architecture in `03-SERVICES-USED.md` | "Detection is solved. Measurement and verification are not. That's what Patchwork adds." |
| 2 | 1:00 | Play 20 s of the synthetic pass | "This is the real Worli Seaface geometry from OpenStreetMap. Every pothole has a known area to the cm², so we can grade ourselves exactly." |
| 3 | 2:00 | `make upload-demo` → switch to Step Functions, watch the graph | "Upload triggers EventBridge → SQS → Step Functions → Batch on Graviton Spot." |
| 4 | 3:00 | While it runs: show `calibration.png` and `bev_measure.png` | "OpenCV 5 ChArUco calibration, then one homography turns pixels into a 1 cm top-down grid. That's where square metres come from." |
| 5 | 4:00 | Show `seg_examples.jpg` + `parity.md` | "SegFormer-B0 trained on SageMaker, exported to ONNX, running in OpenCV 5's new engine. Here's the parity check against onnxruntime." |
| 6 | 5:00 | Step Functions finished → open the viewer, click 2–3 defects | "Each dot is a defect with m² ± uncertainty, severity, and material at a stated 5 cm thickness. We claim area, not depth." |
| 7 | 6:30 | Results table in `04-RESULTS…` | "Recall, false positives per km on the control section, area error, localisation, all computed by code." |
| 8 | 7:30 | `02-COST-REPORT.md` | "Spend so far by service, and cost per km." |
| 9 | 8:30 | *(stretch)* Run A/B diff | "Same clip, same prompt. Change only the measured area and the agent's plan changes. The vision drives the action, and nothing is filed without a human approval token." |
| 10 | 9:30 | `06-NEXT-STEPS.md` | "Second half: repair verification across passes, the full agent, the console, the 40-scenario evaluation." |

## If something fails live
| Failure | Recovery |
|---|---|
| Step Functions slow (Spot capacity) | Show the previous successful execution (pre-run at T−30) |
| Viewer blank | `make preflight` again; else show `assets/viewer.png` |
| Wi-Fi down | Switch to `assets/demo_recording.mp4` |
