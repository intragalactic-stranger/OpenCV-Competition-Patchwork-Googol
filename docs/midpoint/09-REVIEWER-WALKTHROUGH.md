# Reviewer walkthrough: how to read, explain and show the midpoint

> **For the project owner.** Read this once before the review. It gives the story in plain words, the order in which to show things, the exact file or link for each step, what to say, and short answers to the questions reviewers usually ask.
> All numbers come from generated files (`04-RESULTS`, `02-COST-REPORT`, `07-MODEL-CARD`, `08-SERVICE-MAPPINGS`). If a number here ever differs from those files, the generated files are correct.

## 1. The story in 60 seconds

Mumbai has thousands of potholes. Finding them is a solved problem; any phone app can draw a box around one. What a ward engineer actually needs is different:
- **how big** each one is in **square metres**, which sets the material and the crew;
- **where exactly** it is on a named road;
- **whether it was really repaired** on the next drive.

**Patchwork** turns ordinary dashcam video into that register using **OpenCV 5**. It measures the damage in m² with a calibrated top-down view, places it on the road, and tracks it pass after pass. An **AI agent (Amazon Nova)** then turns the register into repair work packages. It **cannot file anything without a human approving it.**

At the midpoint the **whole chain runs on AWS end to end**: upload a survey → defects measured → stored in a database → shown on a map → agent proposes work → human approves. Every number is checked against exact ground truth.

## 2. What to open, in what order

| If the reviewer asks… | Open | Section |
|---|---|---|
| "What did you build?" | `00-MIDPOINT-SCOPE.md`, then the diagram in `03-SERVICES-USED.md` | – |
| "What works, what doesn't?" | `01-PROGRESS-REPORT.md` | At a glance |
| "Show me results" | `04-RESULTS-AND-OUTPUTS.md` | §1 table, §2 pictures, §3 commentary |
| "Show me it running" | Live viewer https://d3mt6jrs1ynczo.cloudfront.net and the Step Functions console | – |
| "What did you train?" | `07-MODEL-CARD.md` | §1–7 |
| "What did the credits buy?" | `08-SERVICE-MAPPINGS.md` | §0–3 (first half), §5 (second half) |
| "Exact AWS bill?" | `02-COST-REPORT.md` | generated from Cost Explorer |
| "What's next?" | `06-NEXT-STEPS.md` | – |

## 3. The walkthrough (about 12 minutes)

### Stop 1 · The problem and the adaptation (1 min)
- **Show:** `04-RESULTS` §2.0 (corridor map) and §2.1 (synthetic contact sheet).
- **Say:** "We survey a real 28.6 km Mumbai loop: Marine Drive, Coastal Road, Worli Seaface, Haji Ali. The road geometry and the 84 schools, hospitals and bus stops are **real** (OpenStreetMap). Instead of driving it and tape-measuring potholes, we **simulate the dashcam** on that geometry. Every pothole's true area is then known exactly, so we can grade ourselves to the square centimetre. The viewer says clearly that the defects are simulated."
- **Why it's a strength:** real tape measurements have their own error, and you can't drive the same road 8 times on demand. A simulator gives exact truth for area, position *and* repair status.

### Stop 2 · OpenCV 5 geometry: from pixels to square metres (2 min)
- **Show:** `assets/calibration.png`, `assets/bev_measure.png`.
- **Say:** "Step one: calibrate the camera with a ChArUco board (OpenCV 5's 3D module, error 0.16 px). Step two: a homography turns the perspective image into a **top-down grid at 1 cm per pixel**. Area becomes a pixel count. With perfect outlines our geometry is off by only **2.1%** (target 5%)."
- **Also mention:** frame triage keeps **284 frames per km** of 15 fps video and loses **no** defects. Faces and number plates are blurred before anything is stored. Position on the road has a median error of **2.6 m**, better than raw GPS (6.2 m), and it works inside the 3.1 km tunnel.

### Stop 3 · The model (2 min)
- **Show:** `07-MODEL-CARD.md` §7, then `assets/seg_examples.jpg`.
- **Say:** "A SegFormer-B0 segmentation model, trained **on CPU only** on AWS Graviton Spot: 3.9 hours, about $2 of credits. It learned from 4,340 real pothole photos with pixel masks plus our synthetic frames. It runs in **OpenCV 5's new DNN engine** and matches the reference runtime to 0.00002 (target 0.001). The older 4.x-style engine can't load it at all, which is a concrete reason this needs OpenCV 5."
- **Be upfront:** "Accuracy is **0.50 IoU on real photos**. It's a first CPU run and the curve was still rising. The second half trains a bigger model on GPU (see Stop 7)."
- **Point at the worst cases in the figure on purpose.** Showing failures builds trust.

### Stop 4 · The cloud pipeline running (2 min)
- **Show:** `assets/sfn_run.png` (or the live Step Functions console), then the live viewer.
- **Say:** "Uploading a survey *is* the trigger. S3 → EventBridge → Step Functions → AWS Batch runs 10 containers in parallel on Graviton Spot → results go into an Aurora PostgreSQL/PostGIS register → the map updates. One pass of 28.4 km takes **17–19 minutes**, and the perception compute costs **$0.0019 per km** (the proposal's target was under 2 cents)."
- **In the viewer:** click a red dot. Show the **m² ± uncertainty**, the severity, the hot-mix needed (stated assumption: 5 cm patch depth; we never claim to measure depth), the status across passes, and the **evidence image**: the dashcam view plus the measured top-down view.

### Stop 5 · The agent and the human gate (2 min)
- **Show:** `assets/ablation_ab.md`.
- **Say:** "The agent runs on Amazon Nova. It queries the register, groups defects into work packages, ranks them by size and nearby schools and hospitals, estimates material and drafts a work order. It then **can only request approval**. A Step Functions workflow holds a token in the database that the agent never sees. A person approves (a **mock** ticket is filed, nothing goes to a real authority) or rejects (recorded as an override)."
- **The key proof:** "Same pothole, same prompt, same model. We changed **only the measured area**, 0.38 → 3.10 m², and the plan changed: **priority 2 → 1, hot-mix 0.05 → 0.40 t**. So the decisions really come from the vision. This ran on the pipeline's own measurement of a simulated pothole whose true area (0.40 m²) we know exactly."
- **Grounding:** the agent can't invent a defect. Unknown IDs are rejected both by the tools and by a database trigger.

### Stop 6 · Honest results (2 min)
- **Show:** `04-RESULTS` §1 table and §3 commentary, plus `assets/fp_shadows.jpg` and `assets/area_scatter.png`.
- **Say what's green:** recall **0.95** (target 0.85), geometry 2.1%, localisation 2.6 m, OpenCV 5 parity, cost per km, agent A/B.
- **Say what's red, and why:**
  - **False alarms (10 per km):** most are **cast shadows and wet patches**. We put them in the simulator on purpose as traps. A fine-tune with these "look-alikes" as negatives is the fix (see `01-PROGRESS-REPORT` for its status).
  - **Area error end to end (34%):** small potholes are measured well. **Large, shallow depressions** are under-measured because the model marks only their darkest middle. The geometry isn't the problem (2.1% with perfect outlines).
  - **Re-identification across passes (F1 0.57):** this is the basic matcher, and it's confused by the false alarms. The full matcher (ORB features + homography) is second-half work.

### Stop 7 · Money: what was spent, what the second half needs (1 min)
- **Show:** `08-SERVICE-MAPPINGS.md` §0, §1, then §5.
- **Say:** "Every AWS service, what it does, and what it cost, step by step. Everything was paid by **promotional credits**: real money paid is **$0.00**, guarded by a budget alarm. The first half was deliberately run at the cheapest settings, CPU training and everything auto-pausing, to prove the pipeline works. The second half buys accuracy: **GPU training (g6.xlarge with an NVIDIA L4, about 110 GPU-hours)**, the live **40-scenario agent evaluation** on Amazon Nova, an always-on demo database and the console. That's projected at **about $370 of credits (range $260–470)**, line by line, from AWS list prices and our own measured run costs, with caps on every line."

## 4. Questions reviewers are likely to ask

| Question | Short answer | Evidence |
|---|---|---|
| Is any of this real data? | Real road geometry and POIs (OpenStreetMap), real pothole photos for training and testing (Pothole Mix, 4,340 masked images; RDD2022-India). The dashcam passes are simulated so we have exact truth. | `07-MODEL-CARD` §4, `04-RESULTS` §2.1 |
| Won't a model trained on synthetic data fail on real roads? | We report real-photo accuracy separately (0.50 IoU on a held-out real test split), and real photos are 43% of the training images (3,340 of 7,790). Closing the gap is the first second-half item. | Model card §7 |
| Why is the first half so cheap? Will you really need $370? | The first half used CPU training, Spot instances, auto-pausing databases and no always-on services: enough to prove the pipeline. The accuracy work needs GPU training and repeated live agent evaluation, both priced line by line. | `08` §5 |
| Why not GPU now? | A deliberate cost decision for the proof-of-concept. The training code already resumes after Spot interruptions, so moving it to a GPU instance is a configuration change. | `08` §5.1 |
| How do you know the agent isn't hallucinating? | Every defect ID is checked against the database in the tool and by a database trigger. Priority and quantities are computed by code from the register, not by the model. The A/B test shows the plan follows the measurement. | `assets/ablation_ab.md` |
| Could the agent file a complaint by itself? | No. Only the approval workflow can file, and only after a person approves. Filing is a mock ticket (`MOCK-…`) at this stage. | `05-DEMO-GUIDE` step 8 |
| Privacy? | Faces (YuNet) and number plates are blurred before frames are stored. Ground truth is never uploaded with the survey. Raw uploads expire after 30 days. | `03-SERVICES-USED` |
| Why Amazon Nova and not another model? | Owner's decision: first-party AWS models only, fully covered by credits, available in Mumbai through the APAC inference profile. | D-27 in `plan/11` |
| What if a Spot instance is interrupted? | Batch retries the job. Training resumes from its last per-epoch checkpoint in S3. Loading into the register is idempotent, so a re-run creates no duplicates. | `03-SERVICES-USED` |
| What does one km cost? | $0.0019 of perception compute (133 s on 4 vCPU per km at Spot price). | `08` §3 |

## 5. Glossary

| Term | Meaning |
|---|---|
| **IPM / bird's-eye view** | Warping the camera image into a top-down view where 1 px = 1 cm, so area can be measured |
| **ChArUco** | A chessboard with markers, used to calibrate the camera |
| **IoU** | Overlap between the model's outline and the true outline (0–1) |
| **MAPE** | Average percentage error of measured vs true area |
| **Recall** | Share of real defects the system found |
| **Re-ID** | Recognising the same defect again on a later pass |
| **Spot** | Spare AWS capacity at a large discount; can be interrupted |
| **ENGINE_NEW** | OpenCV 5's new DNN inference engine |
| **Task token** | The Step Functions "waiting for a human" mechanism; the agent never holds it |
| **Grounding** | Every claim the agent makes must reference a defect that exists in the database |
