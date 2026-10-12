# Results and outputs

> Every number in this file is written by `make eval-midpoint` (`eval/report.py`), between the markers.
> Images are produced by the pipeline and saved to `assets/`. Nothing here is typed by hand except the commentary.

## 1. Headline metrics vs targets

<!-- METRICS:BEGIN -->
| Metric | Target | Result | Status |
|---|---|---|---|
| Detection recall @ ≤ 1 FP/km (D1) | ≥ 0.85 | [[TBD]] | ⏭ |
| False positives per km, control section (D2) | ≤ 0.5 | [[TBD]] | ⏭ |
| Damaged-area MAPE, end to end (D1) | ≤ 20% | [[TBD]] | ⏭ |
| Damaged-area MAPE, oracle masks (geometry only) | ≤ 5% | [[TBD]] | ⏭ |
| Median localisation error | ≤ 8 m | [[TBD]] | ⏭ |
| Segmentation mIoU (pothole), real images (Indian Roads val) | reported | [[TBD]] | ⏭ |
| Segmentation mIoU (pothole), synthetic val | reported | [[TBD]] | ⏭ |
| ONNX parity: OpenCV 5 ENGINE_NEW vs onnxruntime | ≤ 1e-3 | [[TBD]] | ⏭ |
| Frame triage keep rate | 8–12% | [[TBD]] | ⏭ |
| Processing time per km (Batch, Graviton) | reported | [[TBD]] | ⏭ |
| Cost per km processed | < $0.02 | [[TBD]] | ⏭ |
| Cross-pass re-ID F1, basic matcher (stretch) | ≥ 0.90 (final) | [[TBD]] | 🅿️ |
| Run A/B: plan changes with measured area (stretch) | must change | [[TBD]] | ⏭ |
<!-- METRICS:END -->

## 2. Visual outputs

### 2.1 The synthetic survey (real Mumbai corridor geometry)
![Synthetic contact sheet](assets/synth_contact_sheet.jpg)
*Frames from a rendered pass: arterial potholes, control-section surface, distractors (shadows, wet patches, seams).*

### 2.2 Calibration with ChArUco (OpenCV 5 3D module)
![Calibration](assets/calibration.png)

### 2.3 Perspective → bird's-eye view, measured in m²
![BEV measurement](assets/bev_measure.png)
*Left: undistorted camera frame. Right: metric top-down view (1 cm/px, 1 m grid) with measured footprints and areas.*

### 2.4 Segmentation in OpenCV 5's new DNN engine
![Segmentation examples](assets/seg_examples.jpg)
*Top: real Indian road photos. Bottom: synthetic frames. Failure cases are included on purpose.*

### 2.5 Measured vs true area
![Area scatter](assets/area_scatter.png)

### 2.6 The AWS pipeline running
![Step Functions run](assets/sfn_run.png)

### 2.7 The register on a map
![Map viewer](assets/viewer.png)
Live viewer: [[TBD: CloudFront URL]]

### 2.8 Agent preview: run A vs run B (stretch)
See [`assets/ablation_ab.md`](assets/ablation_ab.md): same clip and prompt, different measured area → different plan.

## 3. Commentary (honest reading of the numbers)

[[TBD: written after the results exist. What works, what doesn't, why, and what the second half does about it.]]
