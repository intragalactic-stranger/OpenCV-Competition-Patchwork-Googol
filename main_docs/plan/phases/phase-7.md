# Phase 7: Console and observability

**Goal:** the full demo runs from a browser: upload → processing → map → defect detail → agent package → approve/reject → before/after.

## Checklist
- [~] Approval console `viewer/console.html` (plain HTML, no build step): work-package list, defects, materials, the agent's work order, approve/reject with note; the map stays `viewer/index.html`. **Deployed** on 2026-10-16 at `/console.html` on the CloudFront site (D-36); tested end to end (sign-in, list, detail, a rejection recorded with the signed-in user) · [ ] filters, history timeline, clip upload
- [~] Auth: Cognito user pool (no self sign-up), hosted UI with PKCE, JWT authorizer on the HTTP API; the approver's name comes from the token (deployed, D-36)
- [x] CloudWatch dashboard for the pipeline (EMF metrics) · [x] failure alarms: any failed pipeline or approval execution, any failed Batch job → email (`modules/alarms`) · [ ] agent metrics on the dashboard
- [ ] X-Ray / OTel: not built; every agent run's full trace is saved as JSON (`eval/results/agent/`, `s3://…/traces/`)

## Exit criteria
- Demo guide steps 1–8 run end to end on the CloudFront URL
- Dashboard screenshot in `main_docs/midpoint/assets/` (or a final-report asset)
