# 10: Roadmap

Two halves. **The first half ends at the grant checkpoint** (the midpoint pack in `docs/midpoint/`).

> **Status (2026-10-14): the first half is done.** Phases 0–4 and 5a met their exit criteria, with the deviations recorded in each [phase checklist](phases/) and the decision log. Two midpoint metrics missed their targets (area MAPE 27.8% vs ≤ 20%; real-photo IoU 0.50 vs aim 0.55); both are in the second-half plan ([midpoint/06](../midpoint/06-NEXT-STEPS.md)).

```
FIRST HALF (midpoint track)                                                SECOND HALF
P0 Foundations ─► P1 Data & synthetic world ─► P2 Geometry ─► P3 Model ─► P4 Cloud pipeline ─► [5a Agent slice] ═► CHECKPOINT
                                                                                                         ║
                         P5 full agent ─► P6 Verification + VLM ─► P7 Console + obs ─► P8 Evaluation ─► P9 Release
```

| Phase | Name | Key deliverable | Exit criteria (all scripted) | Checklist |
|---|---|---|---|---|
| **0** | Foundations | Repo, env, OpenCV 5 verified, AWS access, budget, docs | `make check` green; `ENGINE_NEW` smoke OK; `aws sts get-caller-identity` OK; budget exists | [phase-0](phases/phase-0.md) |
| **1** | Data & synthetic world | Corridor, generator, D1–D4 starter, datasets mirrored, **schema v1 frozen** | One full pass renders with truth; QA contact sheet; `schema-v1` tag | [phase-1](phases/phase-1.md) |
| **2** | Perception geometry | Calibration, undistortion, IPM, triage, privacy, measurement with oracle masks | Oracle-mask area MAPE ≤ 5%; triage keep 8–12%; calibration RMS < 0.5 px | [phase-2](phases/phase-2.md) |
| **3** | Segmentation model | Model trained on Batch (CPU, D-25), ONNX, OpenCV 5 ENGINE_NEW, severity | Parity ≤ 1e-3; mIoU real/synthetic reported; end-to-end MAPE ≤ 20% on D1 | [phase-3](phases/phase-3.md) |
| **4** | Register + cloud pipeline | Terraform stack; S3 → SFN → Batch → Aurora; map viewer | Full-corridor pass processed on AWS; idempotent re-run; viewer URL live | [phase-4](phases/phase-4.md) |
| **5a** | Agent slice (midpoint SHOULD) | 5 tools, AgentCore, approval gate, run A/B ablation | A/B plans differ; approve → mock filing; reject → stops | [phase-5](phases/phase-5.md) |
| ★ | **Grant checkpoint** | `docs/midpoint/*` filled from real outputs; cost report generated; demo rehearsed | Every `[[TBD]]` replaced by a script; demo guide dry-run passes | [midpoint](../midpoint/00-MIDPOINT-SCOPE.md) |
| **5b** | Full agent | Remaining 5 tools, memory, PDF polish, failure handling | 40-scenario harness runs | [phase-5](phases/phase-5.md) |
| **6** | Verification + context | Cross-pass registration, statuses, verify_repair, VLM attributes | Re-ID F1 ≥ 0.90; status acc ≥ 0.90 on D3 | [phase-6](phases/phase-6.md) |
| **7** | Console + observability | Web console, approvals UI, CloudWatch dashboard | Full demo flow in the browser | [phase-7](phases/phase-7.md) |
| **8** | Evaluation | All metrics, scenarios in CI, baselines and ablations table | `make eval` table; ungrounded = 0 | [phase-8](phases/phase-8.md) |
| **9** | Hardening & release | Cost tuning, teardown, recorded demo, release | Fresh deploy + teardown verified | [phase-9](phases/phase-9.md) |

## Working rhythm
- Each phase ends with a **demo + review**: I show the output, and you approve before the next phase starts.
- `docs/midpoint/01-PROGRESS-REPORT.md` is updated at the end of every work session.
- Decisions and deviations go into `11-decisions-and-risks.md` the day they are made.

## Calendar (indicative; adjust to your checkpoint date)
| Week | Phases |
|---|---|
| 1 | P0 + P1 |
| 2 | P2 + P3 (training on Batch Graviton Spot, CPU; D-25) |
| 3 | P4 (+ 5a if on track) → **checkpoint pack** |
| 4–5 | P5b + P6 |
| 6 | P7 + P8 |
| 7 | P9 + buffer |
