# Phase 0: Foundations

**Goal:** a repo, an environment and AWS access we can trust. Every later phase builds on this.
**Midpoint track:** yes.

## Checklist

### Repo and environment
- [x] `git init`, `.gitignore` (data/, .venv/, *.onnx, *.mp4, .terraform/, tfstate)
- [x] `pyproject.toml` (uv, Python 3.12) with dependency groups `dev` and `aws` (`synth`, `train` and `agent` groups are added in their phases)
- [x] `Makefile` targets: `setup`, `check` (ruff + pytest), `test`, `smoke`, `cost-report` (`synth` added in Phase 1)
- [x] Package skeleton `src/patchwork/{schema,synth,perception,register,pipeline,agent,api}`
- [ ] (moved to Phase 1) `config/` with `local.yaml` / `aws.yaml` + `PATCHWORK_ENV` loader

### OpenCV 5 verification (`scripts/smoke/opencv5_smoke.py`)
- [x] Confirm the installed version is 5.x (`cv2.__version__`) and which wheel/variant (contrib needed for ArUco? 5.x layout)
- [x] DNN: build a tiny SegFormer-like ONNX graph with `onnx.helper` (Conv + LayerNorm + MatMul + Softmax + Resize, dynamic H/W) → load with the **new engine** → compare with onnxruntime
- [x] Record the exact engine-selection API (`cv2.dnn.ENGINE_NEW` / `readNet(..., engine=)`) in `06-perception-pipeline.md`
- [x] ChArUco: generate a board → render → detect → `calibrateCamera` round-trip
- [x] YuNet: download the model from OpenCV Zoo → `FaceDetectorYN` runs
- [x] ORB + `findHomography` sanity check

### AWS
- [x] Install AWS CLI v2 and Terraform (user-local, `~/.local/bin`)
- [ ] ⚠️ **User:** attach the instance role (see [09 §1.1](../09-aws-infra-and-cost.md#11-attach-an-iam-role-to-this-ec2-instance))
- [ ] `aws sts get-caller-identity` OK; `aws configure set region ap-south-1`
- [ ] (moved to Phase 5a) Amazon Nova model access check: `aws bedrock list-inference-profiles` → pin the model ID
- [ ] Terraform `bootstrap/` **written and validated** (state bucket with S3-native locking + **Budget $300**, alerts 50/80/100% actual and 100% forecast); `apply` blocked on the instance role
- [ ] Activate the cost-allocation tag `Project` (or ask the payer admin)
- [x] `scripts/cost_report.py` skeleton runs (even with $0)

### Docs
- [x] `docs/README.md`, `docs/plan/*`, `docs/plan/phases/*`, `docs/midpoint/*`

## Findings (2026-10-12)
- **OpenCV 5.0.0** installed from PyPI as `opencv-contrib-python-headless==5.0.0.93` (x86_64 and aarch64 wheels both exist, so the same version runs on Graviton).
- Engine selection API: `cv2.dnn.readNetFromONNX(path, engine)` with `cv2.dnn.ENGINE_AUTO=3`, `ENGINE_CLASSIC=1`, `ENGINE_NEW=2`, plus **`ENGINE_ORT=4`** (an onnxruntime-backed engine, which is useful as a fallback).
- A SegFormer-like graph (Conv, LayerNorm, attention MatMul/Softmax, Resize to input size, **dynamic H×W**) loads in `ENGINE_NEW` and matches onnxruntime to **≤ 4e-6**. **`ENGINE_CLASSIC` fails to import it** (Shape on a dynamic input), which confirms the proposal's reason for OpenCV 5. Evidence: `docs/midpoint/assets/opencv5_smoke.md`.
- ChArUco through a distorted synthetic camera: RMS 0.17 px, fx error 0.04%, k1 −0.2797 vs −0.28.
- The dev box is a **t3a.xlarge in us-east-1** (not ap-south-1), so see D-13.

## Exit criteria
| Check | Command |
|---|---|
| Lint + unit tests green | `make check` |
| OpenCV 5 smoke (DNN new engine, ChArUco, YuNet, ORB) | `make smoke` |
| AWS identity | `aws sts get-caller-identity` |
| Budget exists | `aws budgets describe-budgets --account-id …` |

## Output for the midpoint pack
- Progress report rows: "Repo + env", "OpenCV 5 verified", "AWS foundation + budget".
- Services used so far: S3 (state), DynamoDB (lock), Budgets.
