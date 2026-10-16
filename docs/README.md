# Patchwork: documentation map

> **Patchwork** turns ordinary dashcam video into a measured, map-linked register of road defects (potholes, edge breaks, depressions).
> For each defect it records **how many square metres are damaged** and **whether the defect was actually repaired**.
> An AI agent turns that register into approved work orders.
> Built on **OpenCV 5** and **AWS** for the **OpenCV AI Competition 2026 (Agentic Vision path)**.

---

> **Confused about where to start? Open [`OWNER-CHECKLIST.md`](OWNER-CHECKLIST.md)**: one ordered list of what to open, with paths.

## If you have 5 minutes

| Read | Why |
|---|---|
| [`midpoint/00-MIDPOINT-SCOPE.md`](midpoint/00-MIDPOINT-SCOPE.md) | What we build first, for the halfway grant checkpoint |
| [`midpoint/01-PROGRESS-REPORT.md`](midpoint/01-PROGRESS-REPORT.md) | What is done, in progress and next |
| [`plan/01-project-brief.md`](plan/01-project-brief.md) | The whole idea in plain language, with a glossary |

## Two folders, two audiences

```
docs/
├── OWNER-CHECKLIST.md  the ordered list: what to open before and during the review, and your AWS tasks
├── DATA-LICENSES.md  every dataset, model and map used, with its licence and what it means for release
├── midpoint/     ◄ GRANT CHECKPOINT PACK: show this to the grant reviewers
│   ├── 00-MIDPOINT-SCOPE.md        what is in the halfway demo, and why
│   ├── 01-PROGRESS-REPORT.md       ✅ achieved / 🔄 in progress / ⏭ next   (living document)
│   ├── 02-COST-REPORT.md           money spent so far, by AWS service; cost per km  (generated)
│   ├── 03-SERVICES-USED.md         every AWS service: why, what it does, how it is configured
│   ├── 04-RESULTS-AND-OUTPUTS.md   metrics vs targets, plus pictures of real outputs
│   ├── 05-DEMO-GUIDE.md            step-by-step live demo script and fallback
│   ├── 06-NEXT-STEPS.md            the second half, and what the remaining grant pays for
│   ├── 07-MODEL-CARD.md            the trained model: data, configs, libraries, inputs/outputs, metrics
│   ├── 08-SERVICE-MAPPINGS.md      step by step: which AWS service does what, credits used, second-half projection
│   ├── 09-REVIEWER-WALKTHROUGH.md  START HERE before a review: story, order, what to show and say, Q&A
│   ├── showcase/                   ready to show: captioned screen recording (MP4), 14-slide PDF, screenshots
│   └── assets/                     screenshots, overlays, charts used by the pack
│
└── plan/         ◄ MAIN ENGINEERING PLAN: how the whole thing is built
    ├── 01-project-brief.md         the proposal decoded + glossary
    ├── 02-requirements.md          what "working" means: requirements and metric targets
    ├── 03-architecture.md          components, data flow, AWS diagram
    ├── 04-data-strategy.md         open datasets + the synthetic road generator
    ├── 05-defect-record-schema.md  the data contract between vision and agent
    ├── 06-perception-pipeline.md   every OpenCV 5 stage in detail
    ├── 07-agent-design.md          the Ward Engineer's Assistant: tools, guardrails, approval
    ├── 08-evaluation-plan.md       how we prove it works
    ├── 09-aws-infra-and-cost.md    Terraform, IAM, budget, cost model
    ├── 10-roadmap.md               all phases with exit criteria
    ├── 11-decisions-and-risks.md   decision log + risk register
    └── phases/phase-0 … phase-9    detailed checklists, ticked off as work lands
```

## Status legend used everywhere

| Mark | Meaning |
|---|---|
| ✅ | Done and verified (a command or test proves it) |
| 🔄 | In progress |
| ⏭ | Next up |
| 🅿️ | Parked: deliberately postponed until after the midpoint |
| ⚠️ | Blocked or at risk; the reason is written next to it |
| `[[TBD: …]]` | A number that a script fills in from real runs. Never typed by hand. |

## Source

The original grant proposal (`Proposal.pdf`) is kept by the author and is not part of the public repository.
Where this build deliberately differs from it, the change is listed in [`plan/02-requirements.md`](plan/02-requirements.md#4-what-changed-from-the-proposal-and-why) and [`plan/11-decisions-and-risks.md`](plan/11-decisions-and-risks.md).
