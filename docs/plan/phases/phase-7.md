# Phase 7: Console and observability

**Goal:** the full demo runs from a browser: upload → processing → map → defect detail → agent package → approve/reject → before/after.

## Checklist
- [ ] Console (Vite + MapLibre, static on CloudFront): map, filters (status/severity/road), defect drawer (perspective crop, BEV overlay, history timeline), work-package list, approve/reject with note, upload a clip (presigned S3 PUT), read-only public view
- [ ] Auth: Cognito user pool (engineer role can approve; public role read-only)
- [ ] CloudWatch dashboard: pipeline (km, frames kept, stage timings, cost/km), agent (task success, escalation, **override rate**, time to approval, tokens/$ per work order), errors (DLQ, Batch failures, UNGROUNDED_ID count)
- [ ] X-Ray / OTel trace links from the console to agent runs

## Exit criteria
- Demo guide steps 1–8 run end to end on the CloudFront URL
- Dashboard screenshot in `docs/midpoint/assets/` (or a final-report asset)
