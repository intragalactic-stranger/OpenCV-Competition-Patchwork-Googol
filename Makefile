SHELL := /bin/bash
PY := uv run python

.PHONY: setup check lint test smoke cost-report services-inventory eval-midpoint upload-demo agent-demo ablation approvals scenarios teardown help world bootstrap deploy images report

help:
	@echo "setup        create .venv (Python 3.12) and install deps"
	@echo "check        lint + unit tests"
	@echo "smoke        OpenCV 5 smoke test (DNN ENGINE_NEW, ChArUco, YuNet, ORB)"
	@echo "cost-report  regenerate docs/midpoint/02-COST-REPORT.md from Cost Explorer"
	@echo "services-inventory  list deployed tagged resources into docs/midpoint/03-SERVICES-USED.md"
	@echo "eval-midpoint  regenerate the results table in docs/midpoint/04-RESULTS-AND-OUTPUTS.md"
	@echo "world        build the survey corridor (OpenStreetMap) and the camera calibration"
	@echo "bootstrap    one-time AWS: Terraform state bucket + real-spend budget"
	@echo "images       build the arm64 pipeline, training and agent images and push them to ECR"
	@echo "deploy       terraform apply of the whole stack (infra/terraform/envs/dev)"
	@echo "report       regenerate the final results table (docs/FINAL-REPORT.md)"
	@echo "scenarios    run the 40 live agent scenarios (Amazon Nova)"
	@echo "teardown     remove every Patchwork resource (asks first)"

setup:
	uv sync --python 3.12

lint:
	uv run ruff check src scripts tests eval training

test:
	uv run pytest

check: lint test

smoke:
	$(PY) scripts/smoke/opencv5_smoke.py

cost-report:
	$(PY) scripts/cost_report.py

services-inventory:
	$(PY) scripts/aws/inventory.py

eval-midpoint:
	$(PY) -m eval.report

# demo helpers (see docs/midpoint/05-DEMO-GUIDE.md)
MODEL ?= seg-v3
upload-demo:
	$(PY) scripts/aws/upload_pass.py --seed 11 --pass 1 --model $(MODEL) --clips 5,6 --run demo-$$(date +%H%M%S)

agent-demo:
	PATCHWORK_APPROVAL_SFN=$$(cd infra/terraform/envs/dev && terraform output -raw approval_state_machine) \
	PATCHWORK_ARTIFACTS_BUCKET=$$(cd infra/terraform/envs/dev && terraform output -json buckets | python3 -c "import json,sys; print(json.load(sys.stdin)['artifacts'])") \
	uv run --group agent python -m patchwork.agent.run "Plan repairs for Khan Abdul Gaffar Khan Marg."

ablation:
	uv run --group agent python -m eval.ablation_ab

approvals:
	$(PY) scripts/approve.py list

scenarios:
	uv run --group agent python -m eval.agent.run_scenarios

teardown:
	./scripts/teardown.sh

world:
	$(PY) scripts/setup_world.py

REGION ?= ap-south-1
bootstrap:
	terraform -chdir=infra/terraform/bootstrap init && terraform -chdir=infra/terraform/bootstrap apply

images:
	@REG=$$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$(REGION).amazonaws.com; \
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $$REG && \
	docker buildx build --platform linux/arm64 -f docker/batch.Dockerfile -t $$REG/patchwork-batch:latest --push . && \
	docker buildx build --platform linux/arm64 -f docker/train.Dockerfile -t $$REG/patchwork-train:latest --push . && \
	docker buildx build --platform linux/arm64 -f docker/agent.Dockerfile -t $$REG/patchwork-agent:v1 --push .

deploy:
	terraform -chdir=infra/terraform/envs/dev init && terraform -chdir=infra/terraform/envs/dev apply
	$(PY) scripts/aws/deploy_viewer.py

report:
	$(PY) -m eval.report
