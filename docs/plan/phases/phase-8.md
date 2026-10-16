# Phase 8: Evaluation

**Goal:** every number in the proposal's metric table is produced by code, with baselines and ablations in one table.

## Checklist
- [x] Metrics in `eval/metrics/`: area (oracle + no-rectification ablation), end-to-end, localisation, triage, re-ID (v1 vs v2)
- [x] 40 scenarios in `eval/agent/scenarios.yaml` (12 planning, 8 read-only questions, 12 adversarial, 3 existing work, 2 low confidence, 3 verification), run live on the real register in rolled-back transactions (D-35)
- [ ] Rubric scoring of work-order rationale: not built; the answer check verifies every cited ID instead
- [x] Baseline: area without rectification (same true masks, one fixed m²/pixel scale) → 46.9% MAPE vs 2.1% with the bird's-eye view · [ ] desk-estimated manual survey cost
- [x] Ablations: no IPM (above), matcher v1 vs v2, OpenCV `ENGINE_CLASSIC` (cannot load the model), run A/B (measured area changes the plan) · [ ] no VLM (no VLM built)
- [ ] RDD2022-India external check: used for the privacy check only
- [x] `eval/report.py` → results table into `docs/FINAL-REPORT.md` (and the frozen midpoint table)
- [x] GitHub Actions (`.github/workflows/ci.yml`): lint, unit tests, OpenCV 5 smoke test, scenario re-score from recorded traces with the ungrounded-ID hard gate, `terraform fmt` + `validate`

## Exit criteria
- `make eval` produces the full table with ✅/❌ against targets
- Ungrounded claims = 0
- CI green
