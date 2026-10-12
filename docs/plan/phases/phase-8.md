# Phase 8: Evaluation

**Goal:** every number in the proposal's metric table is produced by code, with baselines and ablations in one table.

## Checklist
- [ ] All metrics in `eval/metrics/` (see [08](../08-evaluation-plan.md))
- [ ] 40 scenarios (`eval/agent/scenarios/*.yaml`) with tool-sequence assertions, including 3 adversarial
- [ ] Rubric scoring of work-order rationale
- [ ] Baselines: bounding box without rectification; desk-estimated manual survey cost
- [ ] Ablations: no IPM, no VLM, no cross-pass registration, classic engine
- [ ] RDD2022-India external check (box-level)
- [ ] `eval/report.py` → results table into the docs (markers)
- [ ] GitHub Actions: `make check` + `make eval-fast` on every push

## Exit criteria
- `make eval` produces the full table with ✅/❌ against targets
- Ungrounded claims = 0
- CI green
