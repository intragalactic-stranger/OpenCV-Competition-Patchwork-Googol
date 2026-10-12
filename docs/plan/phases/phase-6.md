# Phase 6: Verification and context

**Goal:** every known defect gets an honest status on each re-drive (unchanged / repaired / degraded / new / obscured), and defects carry context attributes the agent can reason over.

## Checklist
- [ ] `register_match.py`: GNSS gate (15 m, same segment ±10 m chainage) → ORB on BEV patches → RANSAC homography rigidity check → mask IoU and area delta → status
- [ ] Repaired-patch detector (texture variance + edge-bounded region in the BEV)
- [ ] Obscured detection (specular / water) → re-queue
- [ ] `status_event` with before/after evidence crops
- [ ] `verify_repair` tool: filed package + post-repair pass → verified or escalate
- [ ] VLM attributes: try **OpenCV 5 VLM inference** with a small VLM on defect crops → JSON attributes; fallback to Amazon Nova (multimodal) on Bedrock; third fallback to rules (wheel path from lateral offset, bus stop from POIs)
- [ ] Generate passes 4–8 for D3

## Exit criteria
| Check | Target |
|---|---|
| Re-ID F1 on D3 | ≥ 0.90 |
| Repair-status accuracy on D3 | ≥ 0.90 |
| GNSS-only ablation | reported (shows the value of ORB) |
| VLM attribute agreement with truth tags | reported |
