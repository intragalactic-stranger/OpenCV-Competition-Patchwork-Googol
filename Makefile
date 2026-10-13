SHELL := /bin/bash
PY := uv run python

.PHONY: setup check lint test smoke cost-report services-inventory eval-midpoint help

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
