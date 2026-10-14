# Phase 5: Agent (5a = midpoint slice, 5b = full)

**Goal:** the Ward Engineer's Assistant proposes grounded work packages, waits for a human, and demonstrably changes its plan when the vision output changes.

## 5a: midpoint slice (SHOULD for the checkpoint)
- [x] Confirm the **Amazon Nova** model ID / APAC inference profile in ap-south-1: `apac.amazon.nova-pro-v1:0` (planning), Lite/Micro available; tool use works through Strands
- [x] Tools `query_defects`, `cluster_into_packages`, `estimate_materials`, `draft_work_order`, `request_human_approval` (`agent/tools.py`). **Deviation:** in-process Python functions, not Lambdas yet (same code moves behind AgentCore Gateway in 5b)
- [x] Grounding guard in every tool (`_validate_defects`, `_package` → `UNGROUNDED_ID`) + DB trigger; both verified with a fake ID
- [x] Exposure score + priority (deterministic, PostGIS POI context, in `cluster_into_packages`)
- [x] Strands agent + system prompt (`agent/run.py`, `prompts/system.md`); about 25 s and 12–30 k tokens per run
- [ ] Deploy to AgentCore Runtime; tools via AgentCore Gateway: **moved to the second half** (D-27 trial rule applies). The agent runs from the dev box with the same tools
- [x] Approval state machine (`waitForTaskToken`). **Deviation:** the token is written by Step Functions into Aurora (`approval_request`, decision D-28), not DynamoDB; approve/reject via `scripts/approve.py` (endpoint comes with the console)
- [x] On approve → **mock** ticket (`MOCK-…`) + package `filed`; on reject → `rejected` + override recorded · [ ] `schedule_reinspection` row (5b)
- [~] Work order as **Markdown** in S3 (quantities, assumptions, rationale, confidence, defect IDs; all numbers from the DB). PDF with photo + BEV overlay: 5b
- [x] Trace capture: every tool call, its arguments and result → `eval/results/agent/<run>.json` and `s3://…-artifacts/traces/`
- [x] **`eval/ablation_ab.py`** → `docs/midpoint/assets/ablation_ab.md`: on `seg-v3` pipeline output, 0.35 → 3.10 m² changes priority 2 → 1 and hot-mix 0.046 → 0.401 t

**Exit 5a:** A/B produce different priorities and actions; approve → ticket logged; reject → nothing filed; an unknown ID → rejected. **All four met** (2026-10-14: approve → `MOCK-aea1bb9b…`, reject → override recorded; road-wide demo, 24 packages).

## 5b: full agent (after the checkpoint)
- [ ] Tools: `lookup_context`, `check_existing_tickets`, `file_complaint` (SFN-only), `schedule_reinspection`, `verify_repair`
- [ ] Confidence floor → options mode
- [ ] Failure handling: retries/backoff, degrade to human, `NEEDS_CLARIFICATION`
- [ ] AgentCore Memory for ward preferences
- [ ] Scenario harness skeleton (`eval/agent/`), recorded-response mode for CI

**Exit 5b:** harness runs ≥ 20 scenarios; no ungrounded IDs in any draft.
