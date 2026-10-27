## Inspiration

Every monsoon, Mumbai's roads break up, and every year the city spends hundreds of crores filling potholes: **₹400 crore in 2023 alone**, with more than 59,000 potholes recorded. Across India, pothole-related crashes killed **9,438 people between 2020 and 2024**. Yet the reporting we found was striking: there is **no process to verify that a repair was actually done**, and complaint channels are noisy (in one monsoon period, 4,811 of 10,361 complaints were invalid).

Plenty of apps can put a dot on a map where a pothole is. What a ward engineer actually needs is different: *how big is it, how much asphalt does it need, which one first, and did the contractor really fix it?* We wanted to build that missing layer: **measurement and accountability**, with a human always in charge.

## What it does

**Patchwork turns ordinary dashcam video into a measured, map-linked register of road defects** (potholes, broken road edges, sunken patches), then helps engineers act on it.

- **Measures, not just detects.** OpenCV 5 rectifies the road into a metric bird's-eye view, so each defect gets an area in square metres with an uncertainty, a severity and a hot-mix estimate, e.g. *3.39 m² ± 0.07, high severity, 0.44 t of asphalt*.
- **Puts it on a map.** Every defect has a stable ID, GPS position and road name on a public map with its evidence image.
- **Plans the work.** A *Ward Engineer's Assistant* agent (Amazon Nova on Bedrock AgentCore) groups defects into work packages, ranks them by measured area, severity and nearby schools, hospitals and bus stops, estimates materials and drafts work orders. Every number comes from the database, never from the model.
- **Keeps a human in charge.** Nothing is filed until a named engineer approves it in a signed-in console; rejections are recorded as overrides.
- **Verifies repairs.** On the next drive, each defect is matched again; a filed work order becomes **verified** (gone) or **escalated** (still there).

## How we built it

**Data.** We could not drive Mumbai's roads ourselves, so we built a synthetic dashcam survey on the **real OpenStreetMap geometry** of a 28.6 km loop (Coastal Road, Worli Sea Face, Haji Ali, Marine Drive): a calibrated camera with lens distortion, GNSS and IMU noise, look-alikes (shadows, wet patches, manholes, old patches) and defects that get repaired, degrade or appear between drives. This gives **exact ground truth** for area, position and repair status, so every claim is measured. Real pothole photos (Pothole Mix) teach the model real appearance.

**OpenCV 5 perception**, running in parallel containers on AWS Batch (Graviton Spot):

- ChArUco calibration (`aruco.CharucoDetector`, `calibrateCamera`): 0.16 px reprojection error.
- A road-plane homography, with undistortion folded into a single `remap`, gives a 1 cm/pixel bird's-eye view. A ground point $(X, Y)$ maps to the image as

$$
\tilde{\mathbf{x}} \sim K\,[\,\mathbf{r}_1\;\; \mathbf{r}_2\;\; \mathbf{t}\,]\begin{pmatrix} X \\ Y \\ 1 \end{pmatrix},
$$

  so a damaged area is simply $A = N_{\text{px}} \cdot (0.01\,\text{m})^2$ on the rectified mask, fused as a median over several frames.
- Camera pitch per frame from lane lines (`Canny`, `HoughLinesP`); frame triage with `Laplacian` sharpness and `calcOpticalFlowPyrLK` visual odometry on the road plane; privacy blur with **YuNet** (`FaceDetectorYN`) and a plate/text detector *before anything is stored*.
- Segmentation: a **SegFormer-B2** transformer exported to ONNX with dynamic shapes and run in **OpenCV 5's new DNN engine** (`readNetFromONNX(..., ENGINE_NEW)`). It matches onnxruntime to $3.2\times10^{-5}$; the classic engine cannot load the graph at all.
- Measurement with `findContours` and `minAreaRect`; localisation with a Kalman filter and RTS smoother over GNSS plus optical-flow odometry.

**Training.** SegFormer-B2 on a SageMaker GPU (NVIDIA A10G) in about an hour, then scored through OpenCV 5 on Graviton, the runtime we actually deploy.

**Agent.** Strands + Amazon Nova Pro, hosted on **Amazon Bedrock AgentCore Runtime**, with 9 grounded tools. Priority uses a deterministic, auditable exposure score:

$$
E = w_{\text{sev}}\,\bigl(1+\ln(1+A)\bigr)\,w_{\text{road}}\,\bigl(1 + 0.5\,\mathbb{1}_{\text{school}} + 0.5\,\mathbb{1}_{\text{hospital}} + 0.3\,\mathbb{1}_{\text{bus stop}}\bigr)\, m_{\text{wheel}}\, m_{\text{water}},
$$

where $A$ is the measured area in m², the context indicators count schools and hospitals within 150 m and bus stops within 50 m, and $m_{\text{wheel}}=1.3$, $m_{\text{water}}=1.2$ when a defect is known to sit in a wheel path or hold water (otherwise 1).

**Cloud.** S3 → EventBridge → Step Functions → Batch → Aurora Serverless v2 + PostGIS → CloudFront map; approval via a Step Functions task token, Cognito, API Gateway and Lambda; CloudWatch dashboards (including the **human override rate**) and alarms; everything in Terraform, with CI on every push.

## Challenges we ran into

- **Turning pixels into square metres honestly.** Area in the camera image shrinks with distance. With the same true outlines, measuring without the bird's-eye view gave **46.9% error**; with OpenCV's rectification and per-frame pitch it is **2.1%**.
- **A transformer in OpenCV.** SegFormer's dynamic `Shape` operations break the classic importer; OpenCV 5's new engine was the enabler, and we verified it pixel for pixel against onnxruntime.
- **False alarms.** Shadows, wet patches and manholes look like potholes. We mined "look-alike" frames and trained on them: false alarms on the clean control road fell from 3.9 to **0.25 per km**.
- **Recognising the same pothole a week later.** GNSS is off by metres; we matched on the camera-derived lateral offset (stable to 0.6 m between drives), chainage and area, one-to-one.
- **Keeping an LLM honest.** Three guards stop it citing defects that don't exist: the tools reject unknown IDs, a database trigger rejects bad packages, and the final answer is checked. The approval token never reaches the model, and there is no filing tool.
- **The real world.** Our biggest open challenge: on real wide-angle Indian roadside photos (RDD2022-India) the detector finds only **1%** of potholes. We report it plainly rather than hide it.

## Accomplishments that we're proud of

- On a held-out 56.8 km survey: **99% of defects found**, **area error 13.9%** (median 7.9%, target ≤ 20%), **0.25 false alarms per km** on a clean road, **2.6 m** median position error, **$0.008 per km** to process.
- **Proof that the vision drives the agent:** same pothole, only the measured area changed from 0.20 to 3.10 m², and the plan changed (priority 3 → 1, asphalt 0.03 → 0.40 t).
- **The full loop, live on AWS:** drive 1 → 21 work packages → engineer approves 6 → drive 2 → the agent verifies them: 2 verified, 1 escalated, 3 still open, and **8 of 8 verdicts correct** against ground truth.
- **40 scripted agent scenarios** (including 12 adversarial ones): 39 pass, and **no answer ever cited a defect that does not exist**.
- **0 accessibility violations** (axe-core, WCAG 2.1 AA) on the map and the approval console, which is fully keyboard-operable.
- The whole project ran for about **$32 of AWS usage**, all in Terraform, reproducible from a fresh clone.

## What we learned

- **Separate what you can prove.** Validating the geometry with true outlines (2.1%) before blaming or crediting the network made every later number interpretable.
- **Synthetic data is a measuring instrument**, not just training data: exact truth let us score area, re-identification and repair verification, which real data rarely allows. But it does not replace real footage; our real-photo result taught us that.
- **Agents need structure more than prompts.** Giving each package a deterministic "next step" and grounding every number in the database fixed more failures than any prompt wording.
- **Report failures.** A negative VLM result (no better than a constant answer) and the real-photo gap shaped the design as much as the successes did.

## What's next for Patchwork

- **Real Indian dashcam data:** label pixel masks on real frames and measure against tape-measured potholes. This is the gap between a proven system and a deployable one.
- **Patch-aware repair verification**, so a fresh repair is never mistaken for a pothole.
- **More drives per road** to measure how fast defects degrade, and to plan preventive repairs.
- **Pilot with a ward office:** the console, override tracking and mock filing are designed to be swapped for a real municipal ticketing system once a human team is in the loop.

Code, technical report, live map and video: https://github.com/intragalactic-stranger/OpenCV-Competition-Patchwork-Googol
