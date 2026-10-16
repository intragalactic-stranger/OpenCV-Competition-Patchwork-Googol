# Data, model and map licences

Everything Patchwork uses that was made by someone else, and the terms that come with it. The raw files live in `data/raw/<source>/` (git-ignored) next to a `SOURCE.md` with the URL, the download date and a checksum. This page is the committed copy of those notes.

## Datasets

| Source | Used for | Licence | What it means for us |
|---|---|---|---|
| **Pothole Mix v2** (Ranieri, Moscoso Thompson, Biasotti; SHREC'22). Mendeley Data `10.17632/kfth5g2xk3.2`, zip sha256 `7b95ff42…d74e`, fetched 2026-10-13 | Real photos with pothole masks: training, `val_real`, `test_real` | **CC BY-NC 3.0**; each of the 6 merged sources keeps its own licence (GAPs384: academic use only) | Research / non-commercial only. Model weights trained on it carry the same restriction (D-24). Cite the dataset |
| **RDD2022, India split** (Arya et al., 2024; sekilab, CRDDC'2022). Figshare `21431547`, fetched 2026-10-12 | Privacy-blur check, detection checks. Not used for training (boxes only) | **CC BY-SA 4.0** (the Figshare page says CC BY 4.0; we follow the stricter one) | Attribution; share-alike for anything derived from the images |
| **OpenStreetMap**, Mumbai extract, bbox `18.915,72.795,19.025,72.840`, fetched 2026-10-12 | Survey corridor geometry, road names, schools / hospitals / bus stops near the road | **ODbL 1.0**, © OpenStreetMap contributors | Attribution on the map; derived databases stay ODbL |
| **Synthetic survey** (our generator, seeds 07 and 11) | Training (seed 07), evaluation (seed 11) | Ours: CC BY 4.0 at release | No third-party content in the frames |

Not used: **Indian Roads** (IIT-B e-Yantra), because it is GPL-2.0 and has only 230 pothole images (D-24). **IndiaRDD2022** (Roboflow) was not needed.

## Models

| Model | Used for | Licence | What it means for us |
|---|---|---|---|
| **SegFormer `nvidia/mit-b0`** ImageNet encoder (Hugging Face) | Starting weights for `seg-v1…v3` | NVIDIA Source Code License for SegFormer (**research / non-commercial**) | Our SegFormer weights are research-only and not published (D-07). The licence-clean model `seg-clean-v1` (`--arch lraspp`, torchvision BSD-3 backbone, synthetic data only) is published as a GitHub release (D-39) |
| **torchvision MobileNetV3-Large** ImageNet weights | Backbone of the licence-clean model `seg-clean-v1` | BSD-3 | Attribution |
| **YuNet** face detector, `face_detection_yunet_2023mar.onnx` (OpenCV Zoo) | Privacy blur | MIT | Attribution |
| Plate / text blur | Privacy blur | Our own rule-based detector in `perception/privacy.py` | No third-party model |
| **Amazon Nova Pro / Lite** on Bedrock | Agent; image attributes (evaluated) | AWS service terms | Used as a service; nothing redistributed |

## Map

The viewer uses the Amazon Location Service **Standard** map style; its attribution ("© AWS, HERE") is shown in the map corner. Our own layers (survey loop, schools, hospitals, bus stops) come from OpenStreetMap; the viewer's banner names OpenStreetMap, and the exact ODbL line "© OpenStreetMap contributors" is to be added to the map corner before release.

## Before any public release (Phase 9)
1. Run the privacy blur over every real image kept in our buckets. This has not been done for Pothole Mix yet: the images are road-surface close-ups in a private bucket.
2. Done: code released as Apache-2.0; the `lraspp` weights trained on synthetic data only are released (v1.0); SegFormer weights are not published.
