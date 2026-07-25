# Status — "Fool the Robot" prototype

_Last updated: 2026-07-25_

## TL;DR

Working end-to-end prototype of the confidence core, running live on the M5
MacBook Pro (Apple Silicon, MPS). Camera → CLIP zero-shot → calibrated
confidence bars + independent familiarity gauge, in the browser, with live
tuning sliders and a detection-box object zone. **The core thesis is validated
in principle:** on hard/ambiguous inputs the robot shows honest low confidence
rather than a confident-wrong 99%.

**Not yet done:** the actual empirical calibration pass — pointing clear,
in-vocabulary objects at the box and confirming they read a believable
~75–90% (and tuning temperature/floor until they do). That's the remaining
go/no-go step and needs a human holding objects to the webcam.

## What this prototype is (and isn't)

Scope deliberately narrowed to **confidence concept only** (agreed 2026-07-25):
prove the two-number design on real objects before committing on Monday.

- **In:** camera, CLIP ViT-B/32 on MPS, calibrated softmax, familiarity meter,
  unknown-floor, confidence bands, detection box, live tuning sliders,
  presentable dark UI.
- **Out (deferred, all known-buildable):** voice/TTS, robot face animation,
  challenge deck, leaderboard, celebration, face detection / person deflection,
  operator view, offline packaging, second-laptop setup.

## Hardware decision (settled)

- **Primary: M5 MacBook Pro (16 GB).** Runs CLIP on MPS with large headroom;
  active cooling makes 3-hr thermals a non-issue (still soak-test in week 3).
- **Backup: an M1** the owner has — identical repo, same `device="mps"` path.
  Closes the §10 single-laptop risk.

## Repo layout

```
vision/
  PRD-fool-the-robot.md      # full PRD (updated: §4.2/§5.2b/§5.7 two-number design)
  requirements.txt
  run.sh                     # one-command launcher (chmod +x done)
  server.py                  # FastAPI: /health /video(MJPEG) /ws + capture/inference engine
  config/
    labels.yaml              # 42 display objects (incl. shoe/ball near-neighbors) + 10 anchors
    settings.yaml            # calibration, camera, inference, presence, detection_region
  foolbot/
    classifier.py            # CLIP load (QuickGELU), calibrated classify(), set_tuning()
    camera.py                # cv2 capture, focus/exposure lock, reticle draw, region_box()
  static/
    index.html / style.css / app.js   # two-number UI + tuning sliders
  docs/
    build-brief.md           # the interface contract the 3 build agents worked to
    STATUS.md                # this file
  .venv/                     # Python 3.12; torch 2.13 (MPS), open_clip 3.3, opencv 5.0
```

## How to run

```
cd ~/projects/vision
./run.sh                     # starts server, waits for ready, opens Chrome to the booth
```
Stop: `Ctrl+C` in that terminal, or `pkill -f "uvicorn server:app"`.
Only one instance can hold the webcam at a time — stop the old one before starting a new one.
First launch ~7s (CLIP model load); instant after. Weights are cached locally
(fully offline after the one-time ~350 MB download, already done).

## What's verified

- Full pipeline live on the M5: webcam opens (1280×720), MPS active, WS results
  flowing, MJPEG video, two-number UI rendering, all four bands + idle.
- Random-noise → diffuse ~3% → `confused` (correct: noise isn't confidently anything).
- Person + phone in a wide scene → diffuse ~3%, familiarity LOW, **not** labeled
  as a person (bounded vocab = §9.2 safety property working for free).
- Detection box: green corner-bracket reticle drawn on the feed; CLIP crops to
  exactly that region (shared `region_box()` guarantees draw == classified area).

## Key design decisions captured this session

1. **Two-number UI** (added to PRD §4.2/§5.2b/§5.7): confidence bars ("which of my
   guesses?") PLUS a separate familiarity gauge ("does this look familiar at
   all?"), never two competing percentages. Familiarity = raw top cosine sim
   mapped through the unknown floor; it's what makes "you fooled me" *visible*.
   Chosen variant: **both always visible** (option a). Raw cosine numbers stay
   off the child screen, live in the operator view (parent conversation).
2. **Detection box = fixed center zone**, not object tracking. CLIP doesn't
   localize; a tracking box would need a separate detector (rejected as scope).
   The fixed zone matches the booth's taped mat and fixes confidence dilution.
3. **QuickGELU fix** in the classifier: OpenAI CLIP weights need QuickGELU;
   open_clip 3.3 otherwise loads plain GELU and shifts the raw-sim distribution
   that the floor/familiarity ride on. `force_quick_gelu=True` set.

## Calibration state (the make-or-break knob)

Current defaults in `config/settings.yaml` are **starting guesses, not calibrated**:
`temperature: 15.0`, `similarity_floor: 0.22`, `fam_low_sim: 0.20`, `fam_high_sim: 0.30`,
bands `confident_min: 70`, `confused_max: 40`.

Live tuning sliders in the UI write these in real time (WS `{"type":"tune",...}`).
Targets (PRD §5.2b): clear object ~75–90%; near-neighbor pair (sneaker vs boot)
40–60%; novel object below floor → unknown + LOW familiarity.

## NEXT STEPS (in order)

1. **[human, ~5 min] Empirical read:** hold clear in-vocab objects (shoe, water
   bottle, banana) inside the box, note top-1 %. Then a sneaker+boot pair. Then
   something out-of-vocab (stapler). Report the numbers.
2. **Calibrate live:** drag temperature down if clear objects read ~99%, up if
   too timid; nudge floor until novel objects trip LOW familiarity. Bake the
   values back into `settings.yaml`. (Later: fold into a `scripts/calibrate.py`
   sweep per PRD deliverable #8.)
3. **Go/no-go on the concept** → decide whether to commit and continue the full
   build (voice, robot face, challenges, etc.) per the PRD week plan.
4. **Layout fit:** panel is designed for fixed 1080px; on a shorter window the
   familiarity gauge/sliders need a scroll. Quick fix if it matters on the booth
   monitor — verify at the real kiosk resolution.

## Deadlines

- **Mon Jul 27** — activity name + description to the Alive Center organizer
  for the printed guide. Draft ready in PRD Appendix A.
  (Writing deadline, independent of the build.)
- **Sat Aug 15, 12:00 PM** — setup; event 1–4 PM.
