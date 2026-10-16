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

> **Short on time or no live demo?** Use [`showcase/`](showcase/README.md): a 3-minute captioned screen recording and a 14-slide PDF with the same story and numbers.

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
- **Say:** "A SegFormer-B0 segmentation model, trained **on CPU only** on AWS Graviton Spot in two steps. First a 12-epoch base model (3.9 h). Then a fine-tune (2.7 h) where we showed it 1,788 **look-alikes**: shadows, wet patches, manholes, old repairs, labelled *not damage*. It learned from 4,340 real pothole photos with pixel masks plus our synthetic frames. It runs in **OpenCV 5's new DNN engine** and matches the reference runtime to 0.00002 (target 0.001). The older 4.x-style engine can't load it at all, which is a concrete reason this needs OpenCV 5."
- **Then show `assets/hard_neg_compare.jpg`:** "Same frames, before and after. The shadows are no longer called damage. The manhole on the right still is, and we show that on purpose."
- **Be upfront:** "Accuracy is **0.50 IoU on real photos and 0.57 on synthetic**. It's a small model trained on CPU. The second half trains a bigger model on GPU (see Stop 7)."
- **If asked about Spot:** the fine-tune was interrupted by AWS **three times** and resumed each time from its last checkpoint in S3. The resilience design was tested for real.
- **Point at the worst cases in the figure on purpose.** Showing failures builds trust.

### Stop 4 · The cloud pipeline running (2 min)
- **Show:** `assets/sfn_run.png` (or the live Step Functions console), then the live viewer.
- **Say:** "Uploading a survey *is* the trigger. S3 → EventBridge → Step Functions → AWS Batch runs 10 containers in parallel on Graviton Spot → results go into an Aurora PostgreSQL/PostGIS register → the map updates. One pass of 28.4 km takes **15–17 minutes**, and the perception compute costs **$0.0021 per km** (the proposal's target was under 2 cents)."
- **In the viewer:** click a red dot. Show the **m² ± uncertainty**, the severity, the hot-mix needed (stated assumption: 5 cm patch depth; we never claim to measure depth), the status across passes, and the **evidence image**: the dashcam view plus the measured top-down view.

### Stop 5 · The agent and the human gate (2 min)
- **Show:** `assets/ablation_ab.md`.
- **Say:** "The agent runs on Amazon Nova. It queries the register, groups defects into work packages, ranks them by size and nearby schools and hospitals, estimates material and drafts a work order. It then **can only request approval**. A Step Functions workflow holds a token in the database that the agent never sees. A person approves (a **mock** ticket is filed, nothing goes to a real authority) or rejects (recorded as an override)."
- **The key proof:** "Same pothole, same prompt, same model. We changed **only the measured area**, 0.35 → 3.10 m², and the plan changed: **priority 2 → 1, hot-mix 0.05 → 0.40 t**. So the decisions really come from the vision. This ran on the pipeline's own measurement of a simulated pothole whose true area (0.35 m²) we know exactly."
- **Road-wide run:** "Plan repairs for Khan Abdul Gaffar Khan Marg" → 24 packages in 78 s. Then approve the top one and reject a small one (`make approvals`).
- **If they look closely at the agent's text summary:** it listed one package twice. Say so. The numbers in the database are right, because code computes them, and checking the prose against the register is part of the second-half evaluation.
- **Grounding:** the agent can't invent a defect. Unknown IDs are rejected both by the tools and by a database trigger.

### Stop 6 · Honest results (2 min)
- **Show:** `04-RESULTS` §1 table and §3 commentary (it has a before/after table), plus `assets/hard_neg_compare.jpg` and `assets/area_scatter.png`.
- **Say what's green:** recall **0.94** (target 0.85), **false alarms on the clean control section 0.30 per km (target 0.5)**, geometry 2.1%, localisation 2.6 m, OpenCV 5 parity, cost per km, agent A/B.
- **Say what's red, and why:**
  - **False alarms over the whole survey: 3.1 per km** (was 10 before the fine-tune). Shadows and wet patches, the traps we planted, are mostly fixed. What remains: **manhole covers**, and **one pothole split into two blobs**. The fixes are listed in §3 of `04-RESULTS`.
  - **Area error end to end (27.8%, was 33.7%):** small potholes are measured well (median 18%). **Large, shallow depressions** are still under-measured because the model marks only part of their soft edge. The geometry isn't the problem (2.1% with perfect outlines).
  - **Re-identification across passes (F1 0.73, was 0.57):** this is the basic matcher. It improved because there are fewer false alarms to confuse it. The full matcher (ORB features + homography) is second-half work.
  - **One trade-off:** edge breaks at the kerb are found a little less often (8 of 15 vs 11 of 15). There are very few of them, but we report it.

### Stop 7 · Money: what was spent, what the second half needs (1 min)
- **Show:** `08-SERVICE-MAPPINGS.md` §0, §1, then §5.
- **Say:** "Every AWS service, what it does, and what it cost, step by step. Everything was paid by **promotional credits**: real money paid is **$0.00**, guarded by a budget alarm. The first half was deliberately run at the cheapest settings, CPU training and everything auto-pausing, to prove the pipeline works. The second half buys accuracy: **GPU training (g6.xlarge with an NVIDIA L4, about 110 GPU-hours)**, the live **40-scenario agent evaluation** on Amazon Nova, an always-on demo database and the console. That's projected at **about $370 of credits (range $260–470)**, line by line, from AWS list prices and our own measured run costs, with caps on every line."

## 4. Questions reviewers are likely to ask

| Question | Short answer | Evidence |
|---|---|---|
| Is any of this real data? | Real road geometry and POIs (OpenStreetMap), real pothole photos for training and testing (Pothole Mix, 4,340 masked images; RDD2022-India). The dashcam passes are simulated so we have exact truth. | `07-MODEL-CARD` §4, `04-RESULTS` §2.1 |
| Won't a model trained on synthetic data fail on real roads? | We report real-photo accuracy separately (0.50 IoU on a held-out real test split). Real photos are 3,340 of the 9,578 training images. The look-alike fine-tune also cut false alarms on **real** photos by a quarter to a third. Closing the gap is the first second-half item. | Model card §7 |
| Why is the first half so cheap? Will you really need $370? | The first half used CPU training, Spot instances, auto-pausing databases and no always-on services: enough to prove the pipeline. The accuracy work needs GPU training and repeated live agent evaluation, both priced line by line. | `08` §5 |
| Why not GPU now? | A deliberate cost decision for the proof-of-concept. The training code already resumes after Spot interruptions, so moving it to a GPU instance is a configuration change. | `08` §5.1 |
| How do you know the agent isn't hallucinating? | Every defect ID is checked against the database in the tool and by a database trigger. Priority and quantities are computed by code from the register, not by the model. The A/B test shows the plan follows the measurement. | `assets/ablation_ab.md` |
| Could the agent file a complaint by itself? | No. Only the approval workflow can file, and only after a person approves. Filing is a mock ticket (`MOCK-…`) at this stage. | `05-DEMO-GUIDE` step 8 |
| Privacy? | Faces (YuNet) and number plates are blurred before frames are stored. Ground truth is never uploaded with the survey. Raw uploads expire after 30 days. | `03-SERVICES-USED` |
| Why Amazon Nova and not another model? | Owner's decision: first-party AWS models only, fully covered by credits, available in Mumbai through the APAC inference profile. | D-27 in `plan/11` |
| What if a Spot instance is interrupted? | Batch retries the job. Training resumes from its last per-epoch checkpoint in S3. Loading into the register is idempotent, so a re-run creates no duplicates. | `03-SERVICES-USED` |
| What does one km cost? | $0.0021 of perception compute (147 s on 4 vCPU per km at Spot price). | `08` §3 |
| Did you tune on the test set? | No. The fine-tune's look-alike frames come from the *training* world (seed 07); the evaluation survey is a different world (seed 11). The look-alike check set is a different stretch of road and is never used to pick the model. | `07-MODEL-CARD` §4–5 |

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
| **Hard negatives / look-alikes** | Training images of things that look like damage but are not (shadows, wet patches, manholes), labelled "not damage" |
| **ENGINE_NEW** | OpenCV 5's new DNN inference engine |
| **Task token** | The Step Functions "waiting for a human" mechanism; the agent never holds it |
| **Grounding** | Every claim the agent makes must reference a defect that exists in the database |
