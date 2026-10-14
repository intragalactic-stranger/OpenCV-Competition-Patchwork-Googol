# Showcase for the review team

Everything here can be shown as it is. Rebuild it with one command:
`uv run --with playwright --with imageio-ffmpeg python scripts/showcase/build.py`.

| File | What it is | How to use it |
|---|---|---|
| `Patchwork-midpoint-demo.mp4` | **Screen recording, about 3 min, captioned, no audio.** It shows the live map on AWS: overview, the largest defect with its evidence image, a defect seen on both passes ("unchanged"), one that grew ("degraded"), and the control section. Then it steps through the 14 result slides | Play it when a live demo is not possible, or send it ahead of the meeting. Video files are kept out of git; a copy is kept at `s3://patchwork-682839842398-artifacts/showcase/` |
| `Patchwork-midpoint-slides.pdf` | **The deck, 14 slides**: problem → data → OpenCV 5 geometry → model → fine-tune before/after → cloud pipeline → live map → results table → area scatter → agent A/B → human gate → credits used → second half | Present it full-screen. Every number comes from the generated docs (`04`, `07`, `08`, `02`) |
| `screenshots/slide-NN-*.png` | Each slide as a picture | For email, chat or a document |
| `screenshots/map-NN-*.png` | The live map in five views | Shows that the system really runs on AWS, at https://d3mt6jrs1ynczo.cloudfront.net |

**Suggested 10-minute review:** play the video (3 min), then open the PDF at slide 9 (results) and slide 13–14 (credits) for questions. For deeper questions, use `09-REVIEWER-WALKTHROUGH.md`.

All defects are simulated over real Mumbai roads, and the map and the slides say so. Every "filed" ticket is a mock (`MOCK-…`); nothing is sent to any authority.
