# Run A vs run B: does the measured area change the plan?

Same defect (`01M51907GE77J64SB3BZ6DZ5GM`, Marine Drive, chainage 90 m), same prompt, same model (Amazon Nova Pro, temperature 0). **Only the measured area differs**: in run B the observation was **3.10 m²** instead of the measured **0.20 m²**. Each run ran in its own database transaction, rolled back afterwards.

Register row source: **pipeline output (model seg-v4)**.

**Result: the plan CHANGED ✅**

| | Run A (measured) | Run B (swapped) |
|---|---|---|
| Measured area | 0.20 m² | 3.10 m² |
| Priority (1 = urgent) | 3 | 1 |
| Exposure score | 1.768 | 14.466 |
| Hot-mix needed | 0.0252 t | 0.4007 t |
| Package state | awaiting_approval | awaiting_approval |
| Tool calls | query_defects → check_existing_tickets → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval | query_defects → check_existing_tickets → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval |
| Tokens · seconds | 18113 · 11.9 | 18143 · 13.5 |

## Run A: agent's final answer

> <thinking> The human approval has been requested. Now, I will summarize the package with its priority and the reason for the priority. </thinking>
> 
> The package with ID `01M519E765D50TKSJ04DEMDVDN` has been planned for repair. The priority is set at 3 due to the low severity and small area of the defect. The defect is located on Marine Drive at chainage 89.7 m and is not near any schools, hospitals, or bus stops. The work order has been drafted and human approval has been requested.

## Run B: agent's final answer

> <thinking> The human approval has been requested. Now, I will explain the priority of the package. </thinking>
> 
> The package with ID `01M519EP0WWCG6PW5PEYT4R9Q1` has a priority of 1. This is due to the high severity of the defect `01M51907GE77J64SB3BZ6DZ5GM` on Marine Drive, which has an area of 3.1 m² and is located at chainage 89.7 m. The defect has an exposure score of 14.47, indicating a significant impact on the road's condition. The priority is also influenced by the defect's location, although there are no nearby schools, hospitals, or bus stops within the specified distances.

_Full traces: `eval/results/agent/ablation-A-6DZ5GM.json`, `eval/results/agent/ablation-B-6DZ5GM.json`. Priority and quantities are computed by tools from the database, so the change is caused by the measurement, not by model randomness._
