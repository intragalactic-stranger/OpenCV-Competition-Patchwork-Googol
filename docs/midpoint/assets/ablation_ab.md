# Run A vs run B: does the measured area change the plan?

Same defect (`01M4W2G8G608GKQFEZV0400AET`, Marine Drive, chainage 3193 m), same prompt, same model (Amazon Nova Pro, temperature 0). **Only the measured area differs**: in run B the observation was swapped from **0.35 m²** to **3.10 m²** for the duration of the run (then restored).

Register row source: **pipeline output (model seg-v3)**.

**Result: the plan CHANGED ✅**

| | Run A (measured) | Run B (swapped) |
|---|---|---|
| Measured area | 0.35 m² | 3.10 m² |
| Priority (1 = urgent) | 2 | 1 |
| Exposure score | 5.861 | 21.699 |
| Hot-mix needed | 0.0456 t | 0.4007 t |
| Package state | awaiting_approval | awaiting_approval |
| Tool calls | query_defects → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval | query_defects → cluster_into_packages → estimate_materials → draft_work_order → request_human_approval |
| Tokens · seconds | 12367 · 11.0 | 12359 · 11.0 |

## Run A: agent's final answer

> <thinking> The work order for the defect on Marine Drive has been successfully drafted and submitted for human approval. The defect has a medium severity, an area of 0.3531 m², and is located near two hospitals, making it a priority for repair. The estimated materials required are 0.0177 m³ of hot-mix asphalt. </thinking>
> 
> The work order for the defect on Marine Drive (package_id: 01M4W31G54BM9SBM5VV7RREEEF) has been drafted and submitted for human approval. The defect has a medium severity, an area of 0.3531 m², and is located near two hospitals, making it a priority for repair. The estimated materials required are 0.0177 m³ of hot-mix asphalt.

## Run B: agent's final answer

> <thinking> The work order for the package 01M4W31VPMGVFHPQ66FNYPXZAK has been successfully requested for human approval. I will now summarize the package, its priority, and the reason for its priority. </thinking>
> 
> The work package 01M4W31VPMGVFHPQ66FNYPXZAK on Marine Drive has been requested for human approval. It has a priority of 1 due to its high severity, an area of 3.1 m², and its proximity to two hospitals. The estimated materials for this package are 0.155 m³ of hot-mix asphalt, which will be used to repair the defect 01M4W2G8G608GKQFEZV0400AET.

_Full traces: `eval/results/agent/ablation-A-400AET.json`, `eval/results/agent/ablation-B-400AET.json`. Priority and quantities are computed by tools from the database, so the change is caused by the measurement, not by model randomness._
