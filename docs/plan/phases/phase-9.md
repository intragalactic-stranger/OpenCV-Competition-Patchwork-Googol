# Phase 9: Hardening and release

**Goal:** something a stranger can deploy, run, tear down, and trust.

## Checklist
- [ ] Cost tuning pass (instance types, Aurora min/max ACU, log retention, S3 tiers); final cost/km
- [ ] `make teardown-expensive` and `make teardown` verified on a fresh account/region
- [ ] Fresh `terraform apply` from zero → demo works
- [ ] Recorded fallback demo video (screen capture of the full flow)
- [ ] README with quick start (local and AWS), architecture image, results table
- [ ] Release: code (Apache-2.0), synthetic generator + seeds, schema, 40-scenario suite, synthetic labels (CC-BY); model weights only for the licence-clean model (D-07)
- [ ] Final report (competition submission) built from `docs/`

## Exit criteria
- Fresh deploy + teardown verified, with logs saved
- Submission package complete
