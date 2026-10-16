# 01: Project brief (the proposal, decoded)

## 1. One paragraph

Mumbai has plenty of pothole photographs. What it lacks is a record of **how much road surface is damaged** and **whether last month's damage is still there this month**.
**Patchwork** builds that record from ordinary forward-facing dashcam video, using **OpenCV 5**. It finds each defect, measures its damaged area in **square metres**, places it on a named road, and re-checks it on every later pass.
On top of the record sits an **AI agent**, the *Ward Engineer's Assistant*. It groups defects into repair jobs, estimates materials, ranks jobs by who is at risk, drafts a work order, **waits for a human to approve it**, files it, and schedules a re-inspection to check the repair happened.

## 2. Why it matters

- India, 2023: 480,583 road crashes and 172,890 deaths. 44.8% of the dead were two-wheeler riders and 20.4% pedestrians, the road users least protected from bad surfaces (MoRTH, *Road Accidents in India 2023*).
- Detecting potholes is a solved problem. Turning a photo into a **work order** is not. A ward engineer needs three things a photo cannot give:
  1. **Where, precisely**: a position on a named road, so nine complaints about one stretch become one job.
  2. **How much**: damaged area in m². Patching contracts are priced per m².
  3. **Was it repaired?** Today the only evidence is a photo from the contractor who invoiced. Nobody goes back to measure.
- **Verification creates accountability.** Without it, detection only produces a list.

## 3. The five stages

```
 ┌──────────┐   ┌───────────┐   ┌────────────┐   ┌──────────┐   ┌──────────┐
 │ PERCEIVE │──►│  REGISTER │──►│   DECIDE   │──►│   ACT    │──►│  VERIFY  │──┐
 │ OpenCV 5 │   │  PostGIS  │   │   agent    │   │ human-   │   │ next pass│  │
 │ m², sev. │   │  dedup    │   │ cluster,   │   │ approved │   │ re-measure│  │
 └──────────┘   └───────────┘   │ estimate,  │   │ work     │   └──────────┘  │
       ▲                        │ rank       │   │ order    │                 │
       └────────────────────────┴────────────┴───┴──────────┴─────────────────┘
                         status: unchanged / repaired / degraded / new
```

1. **Perceive (OpenCV 5).** Pick the useful frames, blur faces and number plates, correct lens distortion, and convert the road into a top-down metric view (the "bird's-eye view"). Segment the potholes with a small neural network running in OpenCV 5's **new DNN engine**, then measure each one in m².
2. **Register.** Store every defect in a spatial database, snapped to a named road, with duplicates merged.
3. **Decide.** The agent clusters nearby defects into jobs, converts area into material quantity, and ranks jobs by exposure (schools, hospitals, bus stops, two-wheeler traffic).
4. **Act.** It drafts a PDF work order and **cannot file it without a human approval token**.
5. **Verify.** On the next drive, every defect is re-found and given a status: **unchanged, repaired, degraded or new**. Unrepaired "repairs" are escalated with evidence.

## 4. What is special (what the judges score)

| Claim | How we prove it |
|---|---|
| Vision output **changes the agent's decision** | **Run A / run B ablation.** Same clip, same prompt, only the measured area changes (0.4 m² low vs 3.1 m² high). The plan changes from a routine patch at priority 3 to reinstatement at priority 1 with escalation. Both traces are shown side by side. |
| **Measurement**, not just detection | Area error (MAPE) against ground truth, at most 20% |
| **Verification** of repairs | Cross-pass re-identification F1 ≥ 0.90; repair-status accuracy ≥ 0.90 |
| **Safe agent** | A human approval gate enforced by infrastructure (Step Functions task token). Defect IDs are checked in Lambda, so a hallucinated pothole cannot reach a work order. |
| **Cheap enough for a city** | Cost per km surveyed under US $0.02 |

## 5. How this build differs from the proposal

The proposal assumed a person drives a 25 km Mumbai loop every weekend and measures 300 potholes with a tape.
**This build uses open data plus a synthetic road generator instead.** The generator renders dashcam passes over the **real OpenStreetMap geometry** of the same Mumbai corridor, with potholes of **exactly known area**, and simulates repairs between passes.
This gives *better* ground truth than a tape measure. Real-world generalisation is checked on public Indian road datasets. Details are in [02-requirements §4](02-requirements.md#4-what-changed-from-the-proposal-and-why).

## 6. The survey corridor

Mumbai Coastal Road spine (Marine Drive ↔ Worli interchange), plus feeder arterials through **Worli Seaface, Prabhadevi, Haji Ali and Marine Drive**: about 25 km.
- The **Coastal Road** is new, has almost no defects, and is closed to two-wheelers and pedestrians. It is the **control section** for measuring false positives per km.
- The **feeder arterials** are older and carry two-wheeler and pedestrian traffic. That is where the defects and the risk are.

## 7. Glossary

| Term | Plain meaning |
|---|---|
| **OpenCV 5** | The 2026 major release of the OpenCV computer-vision library. It has a rewritten neural-network engine, better ONNX support (over 80% of operators vs about 22% in 4.x), built-in LLM/VLM support and a reorganised 3D module. |
| **DNN engine / `ENGINE_NEW`** | OpenCV's neural-network runtime. `ENGINE_NEW` selects the new graph-based engine, which handles dynamic shapes and fusion and is CPU-only for now. `ENGINE_CLASSIC` is the old 4.x engine. |
| **ONNX** | A portable file format for trained neural networks. We train in PyTorch, export to ONNX and run it in OpenCV. |
| **SegFormer-B0** | A small transformer model for *semantic segmentation*, which labels every pixel (pothole or not). |
| **Segmentation mask** | A black-and-white image the size of the frame: white where the pothole is. |
| **Camera calibration** | Measuring a camera's lens properties (focal length, distortion) so pixels can be related to real-world geometry. |
| **ChArUco board** | A printed chessboard with ArUco markers used for calibration. OpenCV detects it automatically. |
| **Undistortion** | Straightening the barrel or pincushion curvature a lens adds. |
| **Homography** | A 3×3 matrix that maps points on one plane to another, here road-plane metres ↔ image pixels. |
| **IPM (inverse perspective mapping)** | Using that homography to warp the camera view into a top-down "bird's-eye" view where 1 pixel = a fixed number of centimetres. Area can then be measured directly. |
| **Frame triage** | Throwing away boring or duplicate frames (car stopped, blurry, nothing on the road) before the expensive processing. The target is to keep 8–12%. |
| **YuNet** | A tiny face detector that ships with OpenCV. Used to blur faces for privacy. |
| **ORB** | A fast image-feature detector and descriptor. Used to confirm that two photos from different passes show the same patch of road. |
| **Cross-pass registration** | Matching a defect seen today to the same defect seen last week. |
| **GNSS / IMU** | Satellite positioning (GPS) at 1 Hz, and motion sensors (accelerometer and gyro) at 100 Hz. |
| **PostGIS** | The spatial extension for PostgreSQL. Stores points and lines and answers questions like "what is within 5 m of this?". |
| **Work package** | A group of nearby defects on one road, repaired as one job. |
| **Task token (Step Functions)** | A one-time secret that pauses a workflow until something calls back with it. Here, only the human approval UI can call back. The agent never sees the token. |
| **Grounding** | Every claim the agent makes must cite a real defect ID that exists in the database. This is checked by code, not by the prompt. |
| **AgentCore** | Amazon Bedrock AgentCore: AWS's managed runtime for AI agents (runtime, memory, tool gateway, tracing). |
| **MAPE** | Mean absolute percentage error. "Measured area is off by X% on average." |
| **F1** | A single score combining precision (are matches correct?) and recall (did we find them all?). |
| **Spot instances** | Spare AWS capacity at up to about 70–90% discount, which AWS can reclaim at short notice. |
| **Graviton** | AWS's own Arm-based CPUs. Cheaper per unit of work, and the same architecture as a phone. |
