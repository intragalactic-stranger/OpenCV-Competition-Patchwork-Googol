# Run A vs run B: does the measured area change the plan?

Same defect (`01M4TGEJ8D6EAN8TXV6EGXFG1M`, Marine Drive, chainage 3031 m), same prompt, same model (Amazon Nova Pro, temperature 0). **Only the measured area differs**: in run B the observation was swapped from **0.38 m²** to **3.10 m²** for the duration of the run (then restored).

Register row source: **pipeline output (model seg-v2)**.

**Result: the plan CHANGED ✅**

| | Run A (measured) | Run B (swapped) |
|---|---|---|
| Measured area | 0.38 m² | 3.10 m² |
| Priority (1 = urgent) | 2 | 1 |
| Exposure score | 5.947 | 21.699 |
| Hot-mix needed | 0.049 t | 0.4007 t |
| Package state | awaiting_approval | awaiting_approval |
| Tool calls | query_defects → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval | query_defects → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval |
| Tokens · seconds | 12159 · 10.9 | 12171 · 11.7 |

## Run A: agent's final answer

> <thinking> The work order for package_id 01M4THNX01BYK9AYHZJCQFHEMQ has been successfully drafted and is now awaiting human approval. The priority of this work order is due to the medium severity of the defect, its location on Marine Drive, and its proximity to two hospitals. </thinking>
> 
> The work order for package_id 01M4THNX01BYK9AYHZJCQFHEMQ has been drafted and is now awaiting human approval. The priority of this work order is due to the medium severity of the defect (defect_id 01M4TGEJ8D6EAN8TXV6EGXFG1M), its location on Marine Drive, and its proximity to two hospitals. The estimated materials required for the repair are 0.019 m³ of hot-mix asphalt.

## Run B: agent's final answer

> <thinking> The work order for the defect on Marine Drive at chainage 3031.0 m has been successfully drafted and submitted for human approval. The defect has a high severity, an area of 3.1 m², and is located near two hospitals, making it a priority for repair. The defect has been measured and has a detection confidence of 0.881, indicating a reliable measurement. The work order is now awaiting approval. </thinking>
> 
> The work order for the defect on Marine Drive at chainage 3031.0 m has been successfully drafted and submitted for human approval. The defect has a high severity, an area of 3.1 m², and is located near two hospitals, making it a priority for repair. The defect has been measured and has a detection confidence of 0.881, indicating a reliable measurement. The work order is now awaiting approval.

_Full traces: `eval/results/agent/ablation-A-GXFG1M.json`, `eval/results/agent/ablation-B-GXFG1M.json`. Priority and quantities are computed by tools from the database, so the change is caused by the measurement, not by model randomness._
