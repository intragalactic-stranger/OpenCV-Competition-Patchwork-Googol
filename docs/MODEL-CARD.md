# Model card: road-damage segmentation, `seg-v4` (final)

> **In one sentence:** a neural network looks at the road strip of a dashcam frame and marks every pixel that is road damage (pothole, broken road edge, sunken patch); OpenCV 5 then turns those pixels into square metres.
>
> Sections 1–6 and 8 are written by hand. Section 7 is **generated** by `uv run python -m training.model_card s3://…/models/seg-v4` from the run's own `metrics.json`, `parity.json` and `eval_opencv.json`. The midpoint model (`seg-v3`, SegFormer-B0 trained on CPU) has its own card: [midpoint/07-MODEL-CARD.md](midpoint/07-MODEL-CARD.md).

## 1. What it is for

```
dashcam video → frame triage → privacy blur → [ THIS MODEL: which pixels are damage? ] → bird's-eye view → m² → register → agent
```

- **Its only job is to find damaged pixels.** Measurement is geometry: with true outlines the bird's-eye view measures area to 2.1%, and without it the same outlines give 46.9% (`eval/results/area_oracle.json`, `no_rectification`).
- **It does not** measure area, decide severity, or place the defect on the map; those are deterministic OpenCV steps after it.
- **It runs inside OpenCV 5's new DNN engine** (`cv2.dnn.readNetFromONNX(path, cv2.dnn.ENGINE_NEW)`). PyTorch is used for training only.

## 2. Model

| Item | Value |
|---|---|
| Architecture | **SegFormer-B2** (Xie et al., NeurIPS 2021): MiT-B2 transformer encoder + all-MLP decoder |
| Size | **27 M parameters**, 110 MB as ONNX (B0 was 3.7 M) |
| Starting weights | MiT-B2 encoder pre-trained on ImageNet-1k (`nvidia/mit-b2`, Hugging Face); decoder from scratch |
| Classes | `0 background`, `1 damage` (pothole, edge break, depression); cracks are *ignore* (not area damage) |
| Licence-clean alternative | `--arch lraspp` (LR-ASPP MobileNetV3-Large, BSD weights), implemented, not trained (D-07) |

## 3. Input and output

| | Format |
|---|---|
| **Input** | RGB `float32`, `1 × 3 × H × W`, ImageNet mean/std, H and W multiples of 32. For a 1080p dashcam frame the pipeline feeds the **road strip**, rows 448–896 (about 17 m down to 3.5 m ahead), at 0.75× → **1440 × 336** (padded to 352), exactly as in training (`perception/segment.py` defines it once, decision D-30). Other images: width 960. |
| **Output** | `logits`, `1 × 2 × H/4 × W/4`. OpenCV upsamples, takes the damage probability, thresholds at 0.5 and removes specks < 150 px (`perception/segment.py`). |
| **File** | `s3://patchwork-<account>-artifacts/models/seg-v4/model.onnx` (opset 17, dynamic H/W) with `metrics.json`, `class_map.json`, `parity.json`, `eval_opencv.json`, `best.pt` |

## 4. Training data (open or synthetic; nothing captured by us)

| Source | Images | Licence | Used for |
|---|---|---|---|
| **Pothole Mix v2** (SHREC'22; 6 public sets merged), real photos with pothole masks | 3,340 train / 496 val / 504 test | CC BY-NC 3.0 (GAPs384: academic only). **Research / non-commercial** | train, `val_real`, `test_real` |
| **Patchwork synthetic survey, world seed 07**: dashcam strips over the real Mumbai corridor with exact masks | (in the 9,578 training images) | Ours | train; `val_synth` = a different road stretch (clips 08–09) |
| **Look-alike frames**, seed 07: strips with only shadows, wet patches, manholes, seams, old repairs, speed breakers | 1,788 train / 480 held out (`hard_neg_val`) | Ours | train; `hard_neg_val` |
| Synthetic world **seed 11** | not used in training | Ours | end-to-end test only |

The training set is the same prepared set as `seg-v3` (`s3://…-datasets/train/v3`, 9,578 images), so the change from `seg-v3` to `seg-v4` is the model size and the hardware, not the data. Licences in detail: [DATA-LICENSES.md](DATA-LICENSES.md).

## 5. Training configuration

| Setting | Value |
|---|---|
| Hardware | **GPU**: one SageMaker `ml.g5.2xlarge` (NVIDIA A10G, 24 GB), AWS PyTorch 2.8 container, bf16 autocast (decision D-31). One 25-minute trial job first, then the full run. |
| Run time | 16 epochs × 3.6 min; **1.1 billable hours (≈ $2.0 of credits)**. Hard `MaxRuntime` of 3.5 h. |
| Crop / batch | random 512 × 256 crops (scale 35–100%, half centred on damage), batch 24 |
| Augmentation | flip, exposure ±30, contrast 0.7–1.3, colour cast, blur, sensor noise, JPEG 40–90 |
| Optimiser | AdamW, lr 2e-4 (decoder 10×), weight decay 0.01, polynomial decay (power 0.9) |
| Loss | cross-entropy (damage weight 2, cracks ignored) + soft Dice |
| Model selection | best mean damage IoU over `val_real` and `val_synth`; the look-alike set is reported, never used to choose |
| Evaluation | after training, through **OpenCV 5 on Graviton CPU** (`training/evaluate_job.py` on AWS Batch), the runtime the pipeline uses |
| Reproduce | `uv run python scripts/aws/submit_sagemaker.py --version seg-v4 --backbone nvidia/mit-b2 --epochs 16` |

## 6. Libraries

| Library | Version | Role |
|---|---|---|
| PyTorch | 2.8 (GPU container) / 2.14 (local CPU) | training only |
| Hugging Face transformers | 4.57.6 | SegFormer, MiT-B2 weights |
| ONNX | 1.23.2 | export |
| **OpenCV (opencv-contrib-python-headless)** | **5.0.0** | **inference in the pipeline (`ENGINE_NEW`)** and all image processing |
| onnxruntime | 1.31.0 | parity reference only |

## 7. Results

<!-- MODEL-METRICS:BEGIN -->
**Run:** `s3://patchwork-682839842398-artifacts/models/seg-v4` · architecture `segformer nvidia/mit-b2` · 9578 training images · 16 epochs in 1.0 h on GPU (NVIDIA A10G) · selected epoch **14** (best mean val IoU) · runtime engine for these numbers: **ENGINE_NEW**

| Evaluation set (never used for training) | Images | IoU (damage) | Image recall | False-positive images | ms / image |
|---|---|---|---|---|---|
| Real photos, held-out test split (Pothole Mix test) | 504 | **0.722** | 0.984 | 13 of 318 negatives | 515 |
| Real photos, validation split (Pothole Mix val) | 496 | **0.646** | 0.872 | 18 of 208 negatives | 418 |
| Synthetic Mumbai dashcam strips, held-out road stretch | 1266 | **0.747** | 0.759 | 20 of 719 negatives | 260 |
| Synthetic look-alikes only (shadows, wet, manholes, seams, patches; no damage) | 480 | – | – | **37 of 480** negatives | 260 |

| OpenCV 5 runtime check (same images through both runtimes) | Result |
|---|---|
| ENGINE_NEW loads the model | yes |
| Max difference vs onnxruntime (logits) | 3.2e-05 (target ≤ 1e-3) |
| Pixels with the same decision | 100.0000% |
| ENGINE_CLASSIC (OpenCV 4.x-style importer) | cannot load it (the SegFormer encoder uses dynamic Shape ops, which the classic importer rejects); the pipeline uses ENGINE_NEW, with onnxruntime as fallback |

Training curve (validation IoU after each epoch, measured in PyTorch):

| Epoch | Train loss | IoU val_real | IoU val_synth | Look-alike frames flagged | Minutes |
|---|---|---|---|---|---|
| 0 | 0.7712 | 0.2118 | 0.1889 | 133 | 3.7 |
| 1 | 0.6458 | 0.5164 | 0.4393 | 286 | 3.6 |
| 2 | 0.5336 | 0.4839 | 0.5369 | 113 | 3.6 |
| 3 | 0.4966 | 0.1836 | 0.5387 | 160 | 3.6 |
| 4 | 0.3885 | 0.5841 | 0.4921 | 37 | 3.6 |
| 5 | 0.462 | 0.5336 | 0.5203 | 17 | 3.6 |
| 6 | 0.452 | 0.4665 | 0.5397 | 280 | 3.6 |
| 7 | 0.3451 | 0.4604 | 0.6464 | 40 | 3.6 |
| 8 | 0.3222 | 0.5507 | 0.722 | 34 | 3.6 |
| 9 | 0.3328 | 0.5831 | 0.6855 | 47 | 3.6 |
| 10 | 0.3066 | 0.6269 | 0.7419 | 32 | 3.6 |
| 11 | 0.2967 | 0.6772 | 0.7084 | 160 | 3.6 |
| 12 | 0.2724 | 0.6315 | 0.7645 | 37 | 3.6 |
| 13 | 0.2492 | 0.6928 | 0.7717 | 49 | 3.6 |
| 14 | 0.2267 | 0.7175 | 0.7777 | 53 | 3.6 |
| 15 | 0.2672 | 0.7045 | 0.7784 | 42 | 3.6 |
<!-- MODEL-METRICS:END -->

**seg-v3 (midpoint) → seg-v4 (final)**, same held-out images, same evaluator (OpenCV 5 `ENGINE_NEW` on CPU):

| Held-out set | IoU seg-v3 | IoU seg-v4 | False-positive images seg-v3 | False-positive images seg-v4 |
|---|---|---|---|---|
| Real photos, test (504) | 0.500 | **0.722** | 54 of 318 | **13 of 318** |
| Real photos, val (496) | 0.425 | **0.646** | 55 of 208 | **18 of 208** |
| Synthetic Mumbai, val (1,266) | 0.569 | **0.747** | 23 of 719 | **20 of 719** |
| Look-alikes only, no damage (480) | – | – | 41 of 480 | **37 of 480** |

The training data is identical (`train/v3`); the gain comes from the larger encoder (B2, 27 M parameters vs 3.7 M) trained for 16 epochs on a GPU in about an hour. Real-photo IoU now passes the 0.55 aim and synthetic IoU is at the 0.75 aim (0.747). The price is speed on CPU (see §8).

**How to read these:** IoU is the overlap between predicted and true damage pixels (0–1; above 0.7 is good). Image recall is the share of damaged images where damage was found. Parity is the largest difference between OpenCV's and onnxruntime's outputs; below 1e-3 the two are the same model.


## 8. Known limits

- **Licence:** trained on Pothole Mix (research / non-commercial) and an NVIDIA research-licensed encoder, so the weights are **not released**; the code is Apache-2.0 ([DATA-LICENSES.md](DATA-LICENSES.md)).
- **Speed on CPU:** B2 is about 5.5× slower than B0 per frame in OpenCV on CPU. The pipeline still costs under 2 ¢/km (see the final report), but it is the main cost of a survey.
- **Domain gap:** most real training photos are not Indian dashcam views; Indian-road accuracy is measured on the synthetic Mumbai frames.
- **Cracks are not detected by design.**
