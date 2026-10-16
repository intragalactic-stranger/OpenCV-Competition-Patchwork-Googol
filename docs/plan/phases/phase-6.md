# Phase 6: Verification and context

**Goal:** every known defect gets an honest status on each re-drive (unchanged / repaired / degraded / new / obscured), and defects carry context attributes the agent can reason over.

## Checklist
- [x] Matcher v2 `register/match.py` (D-32): same segment, |Δchainage| ≤ 12 m, |Δlateral offset| ≤ 1.5 m, area ratio ≤ 4×, one-to-one assignment; used by the register and by `eval/metrics/reid.py` · [ ] ORB + homography on bird's-eye patches: not built (the geometric gates already resolve neighbours; the remaining errors are false detections, which appearance matching would not fix)
- [x] `close_pass`: a known defect inside the stretch a pass drove, not re-detected, becomes `repaired` ("not seen again") with a `status_event` · [ ] patch-texture detector: tried rectangularity of the detected outline on the midpoint survey, it does not separate patches (0.67–0.71) from potholes (median 0.71), so not built
- [ ] Obscured detection (specular / water) → re-queue: not built
- [x] `status_event` with evidence (method, previous and new area, last pass seen) · [ ] before/after crops
- [x] `verify_repair` tool: filed package + later pass → `verified` (all defects gone) or `escalated` (some remain)
- [ ] VLM attributes: not built. Context comes from rules (lateral offset) and OpenStreetMap POIs (`lookup_context`)
- [ ] Passes 4–8: not generated; passes 1→2 are evaluated (pass 3 exists for both worlds)

## Exit criteria
| Check | Target |
|---|---|
| Re-ID F1 on D3 | ≥ 0.90 |
| Repair-status accuracy on D3 | ≥ 0.90 |
| GNSS-only ablation | reported (shows the value of ORB) |
| VLM attribute agreement with truth tags | reported |
