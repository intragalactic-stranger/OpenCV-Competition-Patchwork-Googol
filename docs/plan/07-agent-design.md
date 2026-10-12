# 07: Agent design: the Ward Engineer's Assistant

## 1. Purpose

A register of thousands of rows helps nobody. The agent turns **measurements into approved work** and then **goes back to check the work**. The question it must answer is not "is there a pothole?" but **"what should the ward do next, and why?"**

## 2. Runtime

| Piece | Choice |
|---|---|
| Agent loop | **Strands Agents SDK** (Python) deployed to **Bedrock AgentCore Runtime** |
| Model | **Amazon Nova** on Amazon Bedrock in ap-south-1 (Nova Pro for planning, Nova Lite/Micro for cheap sub-steps; APAC cross-region inference profile if needed). Model ID pinned in `config/agent.yaml`, confirmed with `aws bedrock list-inference-profiles` (decision D-17). |
| Tools | **AWS Lambda** functions exposed through **AgentCore Gateway** (MCP). Also callable directly in local tests. |
| Memory | AgentCore Memory: short-term per session; long-term "ward preferences" (for example the approved patch thickness) |
| Tracing | AgentCore observability + OpenTelemetry spans → CloudWatch / X-Ray; full JSON trace to `s3://…/traces/<run_id>.json` |
| Approval | **Step Functions** standard workflow with `.waitForTaskToken` |

## 3. Tools

| Tool | Input | Output | Guard |
|---|---|---|---|
| `query_defects` | bbox or road name, date range, min area, status filter | List of defect records (schema §7) | Read-only |
| `cluster_into_packages` | `defect_ids[]`, max gap (m, default 30) | Packages: same road segment, contiguous chainage | **IDs validated** against Aurora |
| `estimate_materials` | `defect_ids[]` or `package_id`, thickness (m) | m³, tonnes, wastage, **assumption text** | IDs validated; thickness 0.02–0.15 m |
| `lookup_context` | `package_id` or point | Nearby POIs (schools, hospitals, bus stops ≤ 150 m), road hierarchy, two-wheeler exposure class | From PostGIS `poi` + Amazon Location |
| `check_existing_tickets` | `package_id` | Open tickets/packages overlapping the chainage | Prevents duplicates |
| `draft_work_order` | `package_id`, rationale, priority | PDF in S3 (photo, rectified overlay, quantities, assumptions, rationale, confidence) | Every number in the PDF is pulled from the DB by ID, never from model text |
| `request_human_approval` | `package_id` | `{approval_id, state:"awaiting_approval"}` | Starts the SFN execution; **token stored server-side, never returned** |
| `file_complaint` | `approval_id` | Ticket ref (mock) | **Only callable by Step Functions after approval.** Not exposed to the model as a direct action. If the model asks, the Gateway returns `NOT_PERMITTED`. |
| `schedule_reinspection` | road segment, chainage range, reason | `reinspection_id` | |
| `verify_repair` | `package_id` | Status per defect after the latest pass + before/after evidence; escalation recommendation | |

**Midpoint subset (Phase 5a):** `query_defects`, `cluster_into_packages`, `estimate_materials`, `draft_work_order`, `request_human_approval`.

## 4. Human control

1. **Nothing leaves the system unapproved.** Filing and notification run inside the Step Functions approval workflow, after `SendTaskSuccess` from the console. The agent has no IAM permission for `states:SendTaskSuccess` and never sees a token.
2. **Confidence floor** (default 0.6, from detection × severity confidence × localisation quality). Below the floor, the agent must produce *options* ("re-inspect first" vs "patch now"). The work order states "LOW CONFIDENCE: options presented, no recommendation".
3. **Grounding at the tool boundary.** Each tool Lambda runs `SELECT defect_id FROM defect WHERE defect_id = ANY($1)` and rejects any unknown ID with `UNGROUNDED_ID` before doing anything. The DB trigger (schema §5) is the second line of defence. A hallucinated pothole cannot become a work order because the plumbing will not carry it.
4. **Overrides are first-class data.** A rejection or edit is stored as `approval.is_override = true` and drives the **human override rate** on the dashboard front page.

## 5. Prioritisation (exposure score)

```
exposure = severity_w (low 1, med 2, high 4)
         × area_factor (1 + log1p(total_area_m2))
         × road_w (primary 1.5, secondary 1.2, tertiary/residential 1.0, Coastal Road 0.6 — no 2-wheelers/peds)
         × (1 + 0.5·school_150m + 0.5·hospital_150m + 0.3·bus_stop_50m)
         × (1.3 if wheel_path) × (1.2 if water_pooling)
priority 1: exposure ≥ 12 or any high-severity in wheel path near school/hospital
priority 2: 5 ≤ exposure < 12
priority 3: otherwise
```
The model is asked to *explain* the ranking in the work order. The score itself is computed by a tool, so it is deterministic and auditable.

## 6. The run A / run B ablation (proof that vision changes the action)

`eval/ablation_ab.py`:
1. Take one clip and one defect. Run the full pipeline → measured (for example) 0.4 m², low.
2. **Run A**: agent with the real register row.
3. **Run B**: the *same* everything, except the observation is substituted with 3.1 m², high (a DB fixture swap, recorded in the trace).
4. Expected: A → routine patch, priority 3, no escalation. B → larger reinstatement, priority 1, notify the executive engineer, barricade flag.
5. Output: a side-by-side HTML/Markdown diff of both traces (tool calls, arguments, final plan), saved to `docs/midpoint/assets/ablation_ab.*`.
6. **If the plan does not change, the agent is not using the vision.** This is a failing test.

## 7. Failure handling

| Situation | Behaviour |
|---|---|
| Tool timeout / 5xx | Retry with exponential backoff (3×, jitter), then degrade: "present for human decision" |
| Ambiguous road match | Refuse and ask (`NEEDS_CLARIFICATION`) |
| `detected_not_measured` defects | Listed but **excluded** from quantities; the work order says why |
| Prompt injection in data (for example a road name or note field containing instructions) | Tool outputs are wrapped as data. Filing is impossible without a token anyway. Covered by 3 adversarial scenarios. |
| Model output fails JSON or schema validation | One repair attempt, then hand off to a human |

## 8. Observability (what the dashboard shows)

Task success, escalation rate, **human override rate (front page)**, mean time to approval, tool error rate, tokens and $ per work order, ungrounded-ID rejections (should be > 0 in adversarial tests, 0 in normal runs).

## 9. System prompt skeleton (`src/patchwork/agent/prompts/system.md`)

- Role: assistant to a BMC ward engineer. Objective: safe, cost-effective, verified repairs.
- Hard rules: cite `defect_id` for every claim; never state depth; never claim filing happened unless the tool says so; below the confidence floor, present options.
- Output contract: structured `WorkPackagePlan` JSON (validated) + human-readable rationale.
