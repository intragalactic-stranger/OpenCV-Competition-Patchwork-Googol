# Run A vs run B: does the measured area change the plan?

Same defect (`01M4T0M9DC6SA3ZQAZ0SW9S1RC`, Marine Drive, chainage 50 m), same prompt, same model (Amazon Nova Pro, temperature 0). **Only the measured area differs**: in run B the observation was swapped from **0.25 m²** to **3.10 m²** for the duration of the run (then restored).

Register row source: **ground-truth fixture (eval/agent_fixture.py), used until the pipeline has populated the register**.

**Result: the plan CHANGED ✅**

| | Run A (measured) | Run B (swapped) |
|---|---|---|
| Measured area | 0.25 m² | 3.10 m² |
| Priority (1 = urgent) | 3 | 1 |
| Exposure score | 1.829 | 14.466 |
| Hot-mix needed | 0.0317 t | 0.4007 t |
| Package state | awaiting_approval | awaiting_approval |
| Tool calls | query_defects → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval | query_defects → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval |
| Tokens · seconds | 12283 · 11.5 | 11944 · 10.7 |

## Run A: agent's final answer

> <thinking> The work order has been successfully requested for human approval. Here is the summary of the package: </thinking>
> 
> **Summary:**
> - **Package ID:** 01M4T0Z4Y3E9EKMBC442YFWW90
> - **Priority:** 3
> - **Rationale:** The defect on Marine Drive at chainage 50.0m has a low severity but covers an area of 0.245m². Despite its low severity, it is important to address this defect to maintain the road's integrity and ensure safety for pedestrians and vehicles. The defect is located on a major road, and although there are no nearby schools, hospitals, or bus stops, it is still a significant area that requires attention.
> 
> The work order is now awaiting approval.

## Run B: agent's final answer

> <thinking> The work order for the package has been successfully requested for human approval. Here is the summary of the package: </thinking>
> 
> Package ID: 01M4T0ZH0FGXDR2E7Z5778KX5S
> Priority: 1
> Rationale: The defect on Marine Drive at chainage 50.0m has a high severity and an area of 3.1m². Given its location on a major road and the high exposure score of 14.47, this repair is a priority to ensure road safety and maintainability.
> 
> The work order is now awaiting approval.

_Full traces: `eval/results/agent/ablation-A-W9S1RC.json`, `eval/results/agent/ablation-B-W9S1RC.json`. Priority and quantities are computed by tools from the database, so the change is caused by the measurement, not by model randomness._
