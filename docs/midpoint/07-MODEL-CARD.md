# Model card: the road-damage segmentation model

> **In one sentence:** we trained a small neural network that looks at a dashcam frame and marks every pixel that is road damage (pothole, broken road edge, sunken patch). OpenCV then turns those pixels into square metres.
>
> Sections 1–6 and 8 are written by hand. Section 7 (the numbers) is **generated** by `uv run python -m training.model_card` from the training run's own `metrics.json` and `parity.json`. Nothing in section 7 is typed by hand.

## 1. What it is for (its job in the pipeline)

```
dashcam video → frame triage → privacy blur → [ THIS MODEL: which pixels are damage? ] → bird's-eye view → m² → register → agent
```

- **Why a model at all?** Geometry (calibration + bird's-eye view) can measure any shape exactly, which we proved with oracle masks: 2.1% area error. But something has to *find* the damaged pixels in a real image. That is this model's only job.
- **What it does not do:** it does not measure area, decide severity, or locate the defect on the map. Those are deterministic OpenCV/geometry steps after it, which we can test and explain on their own.
- **Where it runs:** inside **OpenCV 5's new DNN engine** (`cv2.dnn.readNetFromONNX(..., ENGINE_NEW)`). PyTorch is only used for training. At run time the pipeline needs nothing but OpenCV.

## 2. Model

| Item | Value |
|---|---|
| Architecture | **SegFormer-B0** (Xie et al., NeurIPS 2021): a small transformer encoder (MiT-B0) plus an all-MLP decoder |
| Size | **3.7 M parameters**, about 15 MB as ONNX |
| Starting weights | MiT-B0 encoder pre-trained on ImageNet-1k (`nvidia/mit-b0`, Hugging Face); decoder trained from scratch |
| Classes | `0 background`, `1 damage` (pothole, edge break, depression). Cracks are marked *ignore*: they are not area damage, and teaching "crack = pothole" would inflate area |
| Licence-clean alternative | `--arch lraspp`: LR-ASPP MobileNetV3-Large (torchvision, BSD weights). Same pipeline and interface (decision D-07) |

## 3. Input and output

| | Format |
|---|---|
| **Input** | 1 RGB image, `float32`, shape `1 × 3 × H × W`. W = 960, H a multiple of 32. Normalised with ImageNet mean/std. For a 1080p dashcam frame the pipeline feeds the **road strip** (rows 400–912, the 4–12 m measurement band plus margin) resized to **960 × 256**. Training cut exactly the same strip (`training/prepare.py`). |
| **Output** | `logits`, shape `1 × 2 × H/4 × W/4`. OpenCV does the rest (`perception/segment.py`): upsample → softmax → damage probability per pixel → threshold 0.5 → remove specks < 150 px → binary mask at full frame size. |
| **File** | `model.onnx` (opset 17, dynamic H/W, logits only), stored at `s3://patchwork-<account>-artifacts/models/<version>/` with `metrics.json`, `class_map.json`, `parity.json` |

## 4. Training data (all open or synthetic; no data was captured by us)

| Source | What it gives us | Images | Licence | Used for |
|---|---|---|---|---|
| **Pothole Mix v2** (Ranieri, Moscoso Thompson, Biasotti; SHREC'22). Mendeley Data `10.17632/kfth5g2xk3.2` | Real photos with pixel masks of potholes (red) and cracks (green), merged from 6 public sets (pothole600, cracks-and-potholes-in-road, CNR road, crack500, GAPs384, EdmCrack600) | 3,340 train / 496 val / 504 test | CC BY-NC 3.0; each source keeps its own licence (GAPs384: academic use only). **Research / non-commercial.** | train, `val_real`, `test_real` |
| **Patchwork synthetic survey, seed 07** (our generator, `src/patchwork/synth`) | Dashcam frames over the real 28.6 km Mumbai corridor (OpenStreetMap geometry) with **exact** damage masks. Also shadows, wet patches and repaired patches as false-positive traps. | Generated per run (see §7) | Ours (Apache-2.0) | train, `val_synth` |
| Patchwork synthetic, **seed 11** | A *different* world: new defects, new shadows | not used in training | Ours | end-to-end test only (D1) |
| RDD2022 India (Arya et al.) | Real Indian roads, bounding boxes only | 9,665 | CC BY-SA 4.0 | not used for training (no masks); used for the privacy check and detection checks |

**No leakage between training and testing:**
- Synthetic validation uses a different *stretch of road* (clips 08–09, about 4.6 km), not just different frames.
- The end-to-end test uses a different *world* (seed 11).
- Pothole Mix keeps its published train/val/test split.

## 5. Training configuration

| Setting | Value |
|---|---|
| Hardware | **CPU only** (decision D-25): AWS Batch on Graviton Spot, 32 vCPU (c7g/m7g.8xlarge), arm64 container `patchwork-train`. No GPU. |
| Crop / batch | random 512 × 256 crops (scale 35–100% of image width, half centred on damage), batch 16 |
| Augmentation | horizontal flip, exposure ±30, contrast 0.7–1.3, colour cast ±10%, Gaussian blur, sensor noise, JPEG 40–90 |
| Optimiser | AdamW, lr 3e-4 (decoder 10×), weight decay 0.01, polynomial decay (power 0.9) |
| Loss | cross-entropy (damage weight 2, cracks ignored) + soft Dice on the damage class |
| Epochs | 12, or stop at the time budget (6 h). Checkpoint every epoch to S3, so a Spot interruption resumes rather than restarts. |
| Model selection | best mean damage IoU over `val_real` and `val_synth` |
| Reproduce | `docker/train.Dockerfile` → ECR → `scripts/aws/submit_train.py` (see §8) |

## 6. Libraries (exact versions are pinned in `uv.lock`)

| Library | Version | Role |
|---|---|---|
| PyTorch (CPU build) | 2.14.1 | training only |
| torchvision | 0.29.1 | LR-ASPP fallback, ImageNet weights |
| Hugging Face transformers | 4.57.6 | SegFormer implementation and MiT-B0 weights |
| ONNX | 1.23.2 | export format |
| **OpenCV (opencv-contrib-python-headless)** | **5.0.0** | **inference in the pipeline (`ENGINE_NEW`)**, plus all image processing |
| onnxruntime | 1.31.0 | reference for the parity test only |

## 7. Results

<!-- MODEL-METRICS:BEGIN -->
**Run:** `s3://patchwork-682839842398-artifacts/models/seg-v2` · architecture `segformer` · 7790 training images · 12 epochs in 3.9 h on CPU · runtime engine for these numbers: **ENGINE_NEW**

| Evaluation set (never used for training) | Images | IoU (damage) | Image recall | False-positive images | ms / image |
|---|---|---|---|---|---|
| Real photos, held-out test split (Pothole Mix test) | 504 | **0.496** | 0.989 | 73 of 318 negatives | 156 |
| Real photos, validation split (Pothole Mix val) | 496 | **0.419** | 0.913 | 82 of 208 negatives | 125 |
| Synthetic Mumbai dashcam strips, held-out road stretch | 1266 | **0.428** | 0.592 | 64 of 719 negatives | 76 |

| OpenCV 5 runtime check (same images through both runtimes) | Result |
|---|---|
| ENGINE_NEW loads the model | yes |
| Max difference vs onnxruntime (logits) | 2.4e-05 (target ≤ 1e-3) |
| Pixels with the same decision | 100.0000% |
| ENGINE_CLASSIC (OpenCV 4.x-style importer) | cannot load it (the SegFormer encoder uses dynamic Shape ops, which the classic importer rejects); the pipeline uses ENGINE_NEW, with onnxruntime as fallback |

Training curve (validation IoU after each epoch, measured in PyTorch):

| Epoch | Train loss | IoU val_real | IoU val_synth | Minutes |
|---|---|---|---|---|
| 0 | 0.9023 | 0.1683 | 0.0662 | 19.0 |
| 1 | 0.8981 | 0.3292 | 0.1387 | 19.1 |
| 2 | 0.8204 | 0.2778 | 0.1151 | 19.1 |
| 3 | 0.7625 | 0.1622 | 0.1566 | 19.1 |
| 4 | 0.6718 | 0.2387 | 0.0795 | 19.0 |
| 5 | 0.6918 | 0.3726 | 0.2877 | 19.2 |
| 6 | 0.6928 | 0.3336 | 0.1788 | 19.2 |
| 7 | 0.5772 | 0.3192 | 0.3042 | 19.2 |
| 8 | 0.5471 | 0.4941 | 0.3223 | 19.1 |
| 9 | 0.4737 | 0.5518 | 0.2537 | 19.1 |
| 10 | 0.4095 | 0.5122 | 0.4346 | 19.2 |
| 11 | 0.4122 | 0.5199 | 0.3793 | 19.2 |
<!-- MODEL-METRICS:END -->

**How to read these:**
- **IoU (damage):** overlap between predicted and true damage pixels, from 0 to 1. Above 0.5 is usable; above 0.7 is good.
- **Image recall:** the share of images containing damage where the model found damage.
- **Parity:** how far OpenCV's output is from onnxruntime on the same input. Below 1e-3 means the same model; the decisions match pixel for pixel.

## 8. Known limits and honest caveats

- **Licence:** the main model learns from Pothole Mix, which is research / non-commercial. The released weights carry that restriction (decision D-24). The `lraspp` model trained on synthetic data only is the licence-clean option.
- **Domain gap:** most real training images are not Indian dashcam views (several are top-down close-ups). Indian-specific accuracy is measured on synthetic Mumbai-geometry frames and checked qualitatively on RDD2022-India images (boxes only, so no IoU is possible there).
- **Cracks are not detected by design.** They are not area damage.
- **Wet patches and fresh shadows** are the main expected false positives. The synthetic set contains them on purpose, and false positives per km on the control section are reported in the results table.
