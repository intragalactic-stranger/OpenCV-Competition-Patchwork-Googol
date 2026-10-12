# Phase 5: Agent (5a = midpoint slice, 5b = full)

**Goal:** the Ward Engineer's Assistant proposes grounded work packages, waits for a human, and demonstrably changes its plan when the vision output changes.

## 5a: midpoint slice (SHOULD for the checkpoint)
- [ ] Confirm the **Amazon Nova** model ID / APAC inference profile in ap-south-1 (`aws bedrock list-inference-profiles`); smoke-test tool use via the Converse API
- [ ] Tool Lambdas: `query_defects`, `cluster_into_packages`, `estimate_materials`, `draft_work_order`, `request_human_approval`
- [ ] Shared `grounding.py` guard (reject unknown IDs → `UNGROUNDED_ID`), used by every tool
- [ ] Exposure score + priority (deterministic, in `estimate_materials`/`cluster` outputs)
- [ ] Strands agent + system prompt; local run against Bedrock with tools called in-process
- [ ] Deploy to AgentCore Runtime; tools via AgentCore Gateway
- [ ] Approval state machine (`waitForTaskToken`), token in DynamoDB only; approve/reject via a minimal endpoint (`POST /approvals/{id}`)
- [ ] On approve → mock `file_complaint` webhook (logged) + `schedule_reinspection` row
- [ ] Work-order PDF (reportlab): photo, BEV overlay, quantities, assumptions, rationale, confidence, defect IDs
- [ ] Trace capture (S3 JSON + CloudWatch)
- [ ] **`eval/ablation_ab.py`** → side-by-side trace diff to `docs/midpoint/assets/`

**Exit 5a:** A/B produce different priorities and actions; approve → ticket logged; reject → nothing filed; an unknown ID → rejected.

## 5b: full agent (after the checkpoint)
- [ ] Tools: `lookup_context`, `check_existing_tickets`, `file_complaint` (SFN-only), `schedule_reinspection`, `verify_repair`
- [ ] Confidence floor → options mode
- [ ] Failure handling: retries/backoff, degrade to human, `NEEDS_CLARIFICATION`
- [ ] AgentCore Memory for ward preferences
- [ ] Scenario harness skeleton (`eval/agent/`), recorded-response mode for CI

**Exit 5b:** harness runs ≥ 20 scenarios; no ungrounded IDs in any draft.
