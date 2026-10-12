# Phase 3: Segmentation model (SageMaker → ONNX → OpenCV 5)

**Goal:** a pothole segmentation model trained on AWS and running inside OpenCV 5's new DNN engine, giving end-to-end area MAPE ≤ 20%.
**Midpoint track:** yes.

## Checklist
- [ ] `training/dataset.py`: Indian Roads (real) + synthetic perspective frames + composites; class map; augmentations (blur, JPEG, rain, exposure)
- [ ] `training/train.py`: HF `SegformerForSemanticSegmentation` (mit-b0), 512×512 crops, AdamW, poly LR, Dice + CE loss; logs mIoU per class, real vs synthetic
- [ ] Licence-clean fallback model: `torchvision.models.segmentation.lraspp_mobilenet_v3_large` (D-07)
- [ ] `training/launch.py`: SageMaker PyTorch Estimator, `ml.g5.xlarge`, **managed Spot**, checkpoints in S3, `max_run` 3 h, tags `Project=patchwork, Phase=3`
- [ ] Quick CPU sanity run locally (tiny subset, 1 epoch) before the first GPU job
- [ ] `training/export_onnx.py`: opset 17, dynamic H/W, onnxsim; **logits only** (resize + softmax done in OpenCV)
- [ ] `training/parity.py`: OpenCV ENGINE_NEW vs onnxruntime (≤ 1e-3), plus a note on whether ENGINE_CLASSIC loads it
- [ ] `perception/segment.py`: blobFromImage, forward, upsample, argmax, morphology; latency benchmark on arm64 (Graviton) and x86
- [ ] `severity.py` v1 rules, then v2 calibrated
- [ ] Model registry: `s3://…-artifacts/models/<version>/` with `model.onnx`, `metrics.json`, `class_map.yaml`, `card.md`
- [ ] Visuals: prediction overlays on real Indian Roads val images + synthetic frames (good and failure cases)

## Exit criteria
| Check | Target |
|---|---|
| ONNX parity (ENGINE_NEW vs onnxruntime) | max \|Δ\| ≤ 1e-3 |
| mIoU pothole: real val / synthetic val | reported (aim ≥ 0.55 / ≥ 0.75) |
| End-to-end area MAPE on D1 | ≤ 20% |
| Recall @ ≤ 1 FP/km on D1 | ≥ 0.85 |
| FP/km on D2 | ≤ 0.5 |
| SageMaker cost of this phase | recorded in the cost report |
