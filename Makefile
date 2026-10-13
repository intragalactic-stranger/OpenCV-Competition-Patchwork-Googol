SHELL := /bin/bash
PY := uv run python

.PHONY: setup check lint test smoke cost-report services-inventory eval-midpoint upload-demo agent-demo ablation approvals help

help:
	@echo "setup        create .venv (Python 3.12) and install deps"
	@echo "check        lint + unit tests"
	@echo "smoke        OpenCV 5 smoke test (DNN ENGINE_NEW, ChArUco, YuNet, ORB)"
	@echo "cost-report  regenerate docs/midpoint/02-COST-REPORT.md from Cost Explorer"
	@echo "services-inventory  list deployed tagged resources into docs/midpoint/03-SERVICES-USED.md"
	@echo "eval-midpoint  regenerate the results table in docs/midpoint/04-RESULTS-AND-OUTPUTS.md"

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
