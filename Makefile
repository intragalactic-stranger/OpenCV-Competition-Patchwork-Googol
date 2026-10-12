SHELL := /bin/bash
PY := uv run python

.PHONY: setup check lint test smoke cost-report help

help:
	@echo "setup        create .venv (Python 3.12) and install deps"
	@echo "check        lint + unit tests"
	@echo "smoke        OpenCV 5 smoke test (DNN ENGINE_NEW, ChArUco, YuNet, ORB)"
	@echo "cost-report  regenerate docs/midpoint/02-COST-REPORT.md from Cost Explorer"

setup:
	uv sync --python 3.12

lint:
	uv run ruff check src scripts tests

test:
	uv run pytest

check: lint test

smoke:
	$(PY) scripts/smoke/opencv5_smoke.py

cost-report:
	$(PY) scripts/cost_report.py
