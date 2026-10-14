# Owner checklist: what to open, in what order

All paths are from the repo root `/home/ubuntu/opencv/`.

## A. Before the review (about 30 minutes, in this order)

- [ ] 1. `docs/midpoint/showcase/README.md`: what is in the showcase folder (1 minute)
- [ ] 2. `docs/midpoint/showcase/Patchwork-midpoint-demo.mp4`: watch the 3-minute video once
- [ ] 3. `docs/midpoint/showcase/Patchwork-midpoint-slides.pdf`: flip through the 14 slides
- [ ] 4. `docs/midpoint/09-REVIEWER-WALKTHROUGH.md`: **the most important one.** What to show, what to say, and answers to likely questions
- [ ] 5. Open the live map, https://d3mt6jrs1ynczo.cloudfront.net, and click a few dots

## B. During the review

- [ ] 6. Play the video (or present the PDF full screen)
- [ ] 7. Show the live map
- [ ] 8. Keep the PDF open at **slide 9** (results) and **slides 13–14** (credits) for questions

## C. If reviewers ask for detail: open the matching file

| They ask about… | Open |
|---|---|
| What is done, what is left | `docs/midpoint/01-PROGRESS-REPORT.md` |
| The numbers (accuracy, false alarms, cost per km) | `docs/midpoint/04-RESULTS-AND-OUTPUTS.md` |
| How the credits were used, and the second-half estimate | `docs/midpoint/08-SERVICE-MAPPINGS.md` |
| The cost table straight from AWS billing | `docs/midpoint/02-COST-REPORT.md` |
| Which AWS services, and why | `docs/midpoint/03-SERVICES-USED.md` |
| The trained model | `docs/midpoint/07-MODEL-CARD.md` |
| What the second half will build | `docs/midpoint/06-NEXT-STEPS.md` |
| A live demo, step by step | `docs/midpoint/05-DEMO-GUIDE.md` |
| Data licences | `docs/DATA-LICENSES.md` |

You don't need `docs/plan/` for the review. It is the engineering detail behind everything above.

## D. Your AWS tasks (only you can do these)

- [ ] 9. **AWS Console → Support Center → Your support cases**: read the reply and paste it to Claude
- [ ] 10. Close the two old SageMaker GPU cases: **179186331200104** (ml.g5.xlarge) and **179186313400853** (ml.g4dn.xlarge). Reply "no longer needed, please close" or click *Resolve case*
- [ ] 11. Once they are closed, tell Claude "go" to file the EC2 GPU Spot quota request for the second half
- [ ] 12. Once a month: **Billing → Credits**, check the balance and expiry date

## E. Claude's remaining task

- [ ] 13. Tomorrow (2026-10-15): re-run `make cost-report` once the last Spot charges appear in billing (expected total ≈ $10.6, all paid by credits), and update `02` and `08`
