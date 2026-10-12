import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cost_report", ROOT / "scripts" / "cost_report.py")
cost_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cost_report)


def test_replace_block_swaps_only_marked_section():
    text = "head\n<!-- X:BEGIN -->\nold\n<!-- X:END -->\ntail\n"
    out = cost_report.replace_block(text, "X", "new line")
    assert out == "head\n<!-- X:BEGIN -->\nnew line\n<!-- X:END -->\ntail\n"


def test_replace_block_missing_marker_fails():
    with pytest.raises(SystemExit):
        cost_report.replace_block("no markers", "X", "body")


def test_report_has_all_markers():
    text = cost_report.REPORT.read_text()
    for name in ("COST-SUMMARY", "COST-BY-SERVICE", "COST-BY-PHASE"):
        assert f"<!-- {name}:BEGIN -->" in text and f"<!-- {name}:END -->" in text
