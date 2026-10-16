# Build, deploy and test

Everything below was run on this project's account. The local part was also re-run on a fresh clone.

## 0. Pinned dependencies

| What | Where | Pinned how |
|---|---|---|
| Python 3.12 packages | `pyproject.toml` + `uv.lock` | exact versions and hashes (`uv sync --frozen`); `requirements.lock.txt` is the same set for pip users |
| OpenCV | `opencv-contrib-python-headless==5.0.0.93` | exact; the x86_64 and aarch64 wheels both exist, so the same build runs on Graviton |
| Key libraries | torch 2.14.1 (local CPU), transformers 4.57.6, onnx 1.23.2, onnxruntime 1.31.0, strands-agents 1.60.0, boto3 1.43 | `uv.lock` |
| GPU training container | `763104351884.dkr.ecr.ap-south-1.amazonaws.com/pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker` | exact tag in `scripts/aws/submit_sagemaker.py` |
| Infrastructure | Terraform ≥ 1.10, AWS provider `~> 6.0` (6.69.1 locked) | `infra/terraform/envs/dev/.terraform.lock.hcl` |
| Container base | `python:3.12-slim` (arm64), uv 0.9 | `docker/*.Dockerfile` |

## 1. Local build and test (no AWS needed, about 15 minutes)

Requirements: Linux or macOS, [uv](https://docs.astral.sh/uv/), Docker (only for images).

```bash
git clone https://github.com/intragalactic-stranger/OpenCV-Competition-Patchwork-Googol.git && cd OpenCV-Competition-Patchwork-Googol
make setup        # Python 3.12 env with the pinned packages, OpenCV 5.0.0
make check        # ruff + 31 unit tests (OpenCV DNN ENGINE_NEW, ChArUco, geometry, schema, matcher)
make smoke        # OpenCV 5 smoke test: ENGINE_NEW vs onnxruntime, ChArUco calibration, YuNet, ORB + homography
make world        # survey loop from OpenStreetMap + camera calibration (RMS 0.16 px)

# render 2 km of synthetic survey with exact ground truth, then check the geometry with true outlines
uv run python -m patchwork.synth --seed 7 --passes 1 --segment "Khan Abdul Gaffar Khan Marg" --max-m 2000
uv run python -m eval.metrics.area --oracle data/synth/seed07/pass_1     # ≈ 2% area error; no-rectification ≈ 47%

# offline re-score of the 40 recorded agent runs (what CI does)
uv run python -m eval.agent.run_scenarios --rescore
```

Perception on a clip with a model (the licence-clean model is downloadable from the v1.0 release):

```bash
gh release download v1.0 -p seg-clean-v1.onnx -D models/
uv run python -m patchwork.pipeline.runner perceive data/synth/seed07/pass_1/clip_00 --model models/seg-clean-v1.onnx --out runs/local
uv run python -m patchwork.pipeline.runner assemble data/synth/seed07/pass_1 --model models/seg-clean-v1.onnx --out runs/local --overlays
```

## 2. Deploy to AWS (about 45 minutes the first time)

Requirements: an AWS account, Terraform ≥ 1.10, Docker with `buildx` (arm64 images build under QEMU on x86), credentials with `PowerUserAccess` plus IAM rights limited to `patchwork-*` roles (`infra/iam/`). Region: `ap-south-1`.

| Step | Command | Creates |
|---|---|---|
| 1. Bootstrap (once) | put `alert_emails = ["you@example.com"]` in `infra/terraform/bootstrap/terraform.tfvars`, then `make bootstrap` | Terraform state bucket (S3-native locking), real-spend budget alarm |
| 2. Permissions boundary | create `patchwork-boundary` from `infra/iam/patchwork-boundary.json` | the boundary every Patchwork role carries |
| 3. Stack | set the state bucket name in `infra/terraform/envs/dev/main.tf` (`backend "s3"`), put `alert_emails` in `infra/terraform/envs/dev/terraform.tfvars`, then `make deploy` with `agent_image_tag = ""` the first time | VPC (no NAT), S3, ECR, Batch (Graviton Spot), Step Functions, EventBridge, Aurora Serverless v2 + PostGIS, CloudFront map, Cognito + API + Lambda console, AgentCore runtime role, SageMaker role, alarms, dashboard |
| 4. Images | `make images` | arm64 pipeline, training and agent images in ECR |
| 5. Agent runtime | `make deploy` again (default `agent_image_tag = "v1"`) | Bedrock AgentCore runtime |
| 6. Register | `uv run python -m patchwork.register.dataapi migrate && uv run python -m patchwork.register.dataapi load-corridor` | schema v1.1 + roads and points of interest |
| 7. Data + model | render worlds on Batch (`scripts/aws/submit_synth.py`), prepare and train (`scripts/aws/submit_train.py`, or GPU: `scripts/aws/submit_sagemaker.py --version seg-v4 --backbone nvidia/mit-b2`) | datasets in S3, `models/<version>/` |
| 8. Run a survey | `uv run python scripts/aws/upload_pass.py --seed 11 --pass 1 --model seg-v4 --run demo` | upload → pipeline → register → map, about 45 min per 28 km pass |
| 9. Plan and approve | `uv run python scripts/aws/invoke_agent.py "Plan repairs for Hughes Road."`, then decide in the console | work packages, approval requests, mock tickets |
| 10. Console login | `aws cognito-idp admin-create-user --user-pool-id <pool> --username <name> --temporary-password '<…>' --message-action SUPPRESS` | an engineer account (no self sign-up) |

Remove everything: `make teardown` (empties the buckets, `terraform destroy`, then prints the bootstrap step).

## 3. Tests and evaluation

| Check | Command | Needs |
|---|---|---|
| Lint + unit tests | `make check` | nothing |
| OpenCV 5 smoke test | `make smoke` | internet (downloads YuNet) |
| CI (every push) | `.github/workflows/ci.yml`: lint, tests, smoke, agent re-score with the hard gate, `terraform fmt` + `validate` | GitHub Actions |
| Geometry (true outlines) + no-rectification ablation | `uv run python -m eval.metrics.area --oracle <pass dirs>` | rendered survey |
| End to end vs ground truth | `uv run python -m eval.metrics.end_to_end data/synth/seed11/pass_1 data/synth/seed11/pass_2 --runs runs/e2e-v4` | survey + pipeline output |
| Cross-pass matching v1 vs v2 | `uv run python -m eval.metrics.reid data/synth/seed11 --runs runs/e2e-v4` | same |
| Real photos (RDD2022-India) | `uv run python -m eval.metrics.rdd_india --model runs/seg-v4/model.onnx` | RDD2022 India (`scripts/data/fetch_rdd2022_india.py`) |
| Model through OpenCV 5 + parity | `python -m training.evaluate_job` (Batch) or `uv run python -m training.parity <model.onnx>` | prepared dataset |
| Agent: 40 live scenarios | `make scenarios` | AWS (Bedrock, Aurora); rolled back, nothing left behind |
| Agent: run A/B | `make ablation` | AWS |
| VLM attributes vs truth | `uv run python scripts/vlm_attributes.py --eval --models apac.amazon.nova-lite-v1:0 apac.amazon.nova-pro-v1:0` | AWS |
| Accessibility | axe-core run against the live pages (results in `eval/results/accessibility.json`) | browser |
| Results table | `make report` → `main_docs/FINAL-REPORT.md` | result files |
