# Status — "Fool the Robot" prototype

_Build log last updated: 2026-07-26. Closed out 2026-08-15._

> **Closed 2026-08-15.** The booth ran at the Alive Center's STEM Exploration
> Day and it worked. Nothing below was re-verified afterwards, so read it as the
> build log it is: everything under "NEXT STEPS" was a plan made on 2026-07-26,
> not a list of outstanding obligations. The commits after that date — the arm
> gate, the 90-label vocabulary, `stop.sh` releasing the camera, `setup.sh` and
> the lockfile — landed on top of it and are the state that shipped.
>
> The machine this was built on has been wiped. To stand the booth back up, see
> **Reinstalling from scratch** in the [README](../README.md).

## TL;DR

Working end-to-end prototype of the confidence core, running live on the M5
MacBook Pro (Apple Silicon, MPS). Camera → CLIP zero-shot → calibrated
confidence bars + independent familiarity gauge, in the browser, with live
tuning sliders and a detection-box object zone.

**The calibration pass is done and the core thesis is validated on real
objects.** A clear in-vocab object reads 74% "Pretty sure!"; a near-neighbour
shoe pair splits 6/5/4/4; an out-of-vocab object produces two near-tied guesses
plus a LOW familiarity gauge — the "you fooled me!" moment, working, on a thing
that genuinely isn't in the vocabulary.

**Remaining risk:** out-of-vocab objects separate from real ones by only ~0.004
of cosine similarity. Ordering is perfect across 8 objects but the margin is
inside frame-to-frame noise. A fix is designed and not yet built (see
Finding 1 under Open findings).

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
  server.py                  # FastAPI: /health /video(MJPEG) /ws /debug/capture
  config/
    labels.yaml              # 42 display objects (incl. shoe/ball near-neighbors) + 10 anchors
    settings.yaml            # CALIBRATED 2026-07-26 (temperature 55)
  foolbot/
    classifier.py            # CLIP load (QuickGELU), calibrated classify(), set_tuning()
    camera.py                # cv2 capture, focus/exposure lock, reticle draw, region_box()
  static/
    index.html / style.css / app.js   # two-number UI + tuning sliders
  calib/                     # capture crops + manifest.json (calibration ground truth)
  docs/
    build-brief.md               # the interface contract the 3 build agents worked to
    calibration-2026-07-26.md    # full calibration record + method + open findings
    STATUS.md                    # this file
  .venv/                     # Python 3.12; torch 2.13 (MPS), open_clip 3.3, opencv 5.0
```

## How to run

```
cd ~/projects/vision
./run.sh                     # starts server, waits for ready, opens Chrome to the booth
```
Stop: `Ctrl+C` in that terminal, or `./stop.sh` from anywhere (kills whatever
holds the port, TERM then KILL).
Only one instance can hold the webcam at a time — stop the old one before starting a new one.
First launch ~7s (CLIP model load); instant after. Weights are cached locally
(fully offline after the one-time ~350 MB download, already done).

## Calibration — MEASURED, then INVALIDATED by a vocabulary change

**Read this before trusting any percentage on screen.**

T=55 was measured and confirmed live (mug 74%) against a **52-prompt**
vocabulary. Later the same day the vocabulary grew to **100 prompts** (90 display
+ 10 anchors) to cover what children and accompanying adults actually carry.
Every label shares one softmax denominator, so 48 new competitors push all top-1
percentages down — a clear object would read ~52% instead of 74% at T=55, parking
the booth permanently in "hedging".

`temperature` is therefore now **70.0, an ESTIMATE** (two independent probe
distributions landed at 65 and 71). It has not been checked against a real
object. Everything in the measured table below was taken at T=55 / 52 prompts and
is **historical**, not current behaviour.

To restore a measured state: one `/debug/capture` round over real objects, then
`./.venv/bin/python scripts/calibrate.py --write`. To revert instead, set
`temperature: 55.0` and remove the 48 labels added 2026-07-26.

## Calibration — as measured on 2026-07-26 (52 prompts, historical)

Full record and method: **`docs/calibration-2026-07-26.md`**.

Values now baked into `config/settings.yaml`:

```
temperature: 55.0      (was 15.0 — ~3.5x too low)
similarity_floor: 0.24 (was 0.22)
fam_low_sim: 0.24      (pinned == floor so band and gauge can never disagree)
fam_high_sim: 0.33     (was 0.30)
```

At T=15 every object landed in 4–10%, so the robot sat permanently on
"Wait… I'm confused!" even for a textbook-clear object. Ranking was correct
throughout — only the calibration was wrong.

**T=55 is confirmed live, not just predicted:** the mug reads **74%
`confident`**, against a reconstruction that predicted 65–75% once its own known
downward bias was accounted for. Method and result agree. T≈50–65 all satisfy
the PRD §5.2b targets; 55 is the midpoint. T≥70 is confident-wrong territory.

| Object | in vocab? | sim | top-1 | band |
|---|---|---|---|---|
| scissors | yes | 0.332 | 10% @ T=15 → ~90% @ T=55 | confident |
| water bottle | yes | 0.311 | 9% @ T=15 | confident |
| **mug** | yes | 0.303 | **74% @ T=55** ✅ †| confident |
| sneaker (vs dress shoe/boot/sandal) | yes | 0.290 | 6/5/4/4 @ T=15 | hedging |
| pen | yes | 0.274–0.282 | toothbrush 19 / pen 14 @ T=55 | confused |
| **roll of tape** | **no** | 0.270 | 21 / 19 @ T=55, **LOW fam** ✅ †| confused |
| digital camera | no | 0.268 | — | confused |
| wallet | no | 0.259 | — | confused |

† **UI-read, not endpoint-captured.** These two rows come from screenshots, so
they carry exactly the EMA-smoothing caveat documented under Tooling below. The
conclusion is unaffected — smoothing cannot move 74% out of the predicted 65–75%
band — but they are screen-readings, not measurements. Re-run these two through
`/debug/capture?n=10` at the next opportunity to replace them with real values
(and to produce the first `calib/manifest.json`).

Pen reading as an honest 4-way tie (toothbrush/pen/glue stick/scissors) is
correct behaviour, not a failure — a white cylinder held end-on genuinely is
ambiguous.

## Open findings

1. **The familiarity gauge is riding on the wrong signal (highest risk).**
   Absolute cosine similarity cannot tell "an object I don't know" from
   "nothing at all": an **empty room measures 0.273**, which is *higher* than a
   real roll of tape (0.270) and level with a pen (0.274). Fakes span 0.259–0.270
   and real objects 0.274–0.332, so the whole usable range is ~0.004 wide.

   **Fix is built but not switched on.** `classify()` now computes and reports
   `raw_anchor_sim` and `anchor_margin` (best display label minus best anchor
   label) on every frame, and `familiarity_mode: anchor_margin` in
   `settings.yaml` activates it. The margin separates by *sign*, not degree —
   empty room −0.050, blank wall −0.025, noise +0.011, a banana-ish shape +0.022.
   Default remains `absolute` because `fam_margin_low` / `fam_margin_high` are
   placeholders; they must be set from a real object round before the gauge means
   anything. **This is the one thing to finish before the booth is trustworthy.**

2. **The UI cannot distinguish "disconnected" from "nothing in the zone".**
   Both render as "Show me something!". This directly caused a misdiagnosis
   during calibration (see Finding 3 in the calibration doc, including a
   correction to an explanation that was wrong). Front end needs a distinct
   connection/waking state. The presence gate itself is fine — the same white
   mug on a pale wall classifies at 74%, and a real empty room measures a true
   0.000 edge density, so there is ample headroom. What is still unmeasured is
   edge density with a real object filling the zone.

3. **Panel needs ~1080px height.** At 784px the tuning panel falls below the fold
   and needs a scroll. Verify at the real kiosk resolution.

## Production build — started 2026-07-26

Go/no-go passed; build continued past the confidence core.

| Deliverable | State |
|---|---|
| `scripts/calibrate.py` (PRD #8) | **Done.** Recomputes full sims per crop, sweeps temperature × floor × fam_high with `fam_low` pinned to `floor`, scores per-frame by class, picks the *centre* of a tied plateau rather than a grid corner, and separates un-tunable ranking failures from tunable window failures. `--write` updates `settings.yaml` preserving comments, and refuses to write a 0-pass winner. |
| `config/challenges.yaml` (PRD §4.3) | **Done.** 16 cards, each with an operator-only "why" note. Reliability is marked honestly: only 2 of 16 are better than `untested`, because the PRD's claim that drawings and close-ups reliably break CLIP is a prediction, not a measurement on this build. **No consumer yet** — the front end does not read it; run from printed cards for now. |
| `README.md`, `docs/runbook.md`, `docs/signage.md` (PRD #5, #6, #7) | **Done.** Runbook is written for a teen volunteer and marks unbuilt features TBD rather than describing them as working. |
| Voice cascade (PRD §5.4) | **Built and wired.** `foolbot/voice.py` + `config/phrases.yaml` (54 templates, 9 per state) + `scripts/pregenerate_voice.py`. Three tiers: cache → ElevenLabs `eleven_flash_v2_5` (1200 ms deadline) → OS `say` in a killable subprocess (no pyttsx3). Barge-in, 2.5 s cooldown, single pending slot rather than a FIFO. Verified end-to-end in the live server: an attract line spoke through Tier 3. **Tier 2 untested** — no `ELEVENLABS_API_KEY` present; it short-circuits cleanly and never blocks startup. A full render is **1161 utterances / 61,474 characters**, well under the PRD's ~100k estimate — relevant to plan-tier choice. |
| Fool detection, leaderboard, celebration | Not started. |
| Robot face / animations | **Done.** Bottom half of the left column, under the camera feed. Two SVG eyes, expression driven by a class on `#face` set inside `applyBand()` — so the face is fed by the *same* band as the caption and bars and cannot contradict them. Five expressions verified visually: `idle` (slow blink + pupil wander, so a dormant booth still looks alive), `confident` (wide, centred, small pleased bounce), `hedging` (half-lidded, looking away), `confused` (wide, pupils shrunk and darting), `unknown` (searching up and away — baffled, never disapproving), plus `down` (grey, lids nearly shut) for a dropped connection. Pure SVG + CSS, no dependencies, and honours `prefers-reduced-motion`. |
| Operator view + panic key (PRD §5.7) | **Partly done — the arm gate.** `Engine._armed` gates the inference loop, so a disarmed booth does not classify, announce, or run the attract barker; capture keeps running so `/video` stays live and re-arming is instant. Two controls, one flag: `O` (or the on-screen button) is a sticky off/on switch, and holding `Space` while off is a push-to-look peek. Transport is `{"type":"arm","armed":bool,"hold":bool}` on the existing `/ws`, and the server echoes `armed` in every result frame so the panel renders server truth rather than its own keypresses. A hold carries a 1.5 s TTL refreshed by browser keep-alives and is dropped on socket close, so a dead tab or a wedged key cannot leave the booth armed. Disarming resets stability state so re-arming cannot announce a stale object. Off is a distinct third UI state (✋ "Robot is resting"), never conflated with idle or disconnected. **Not done:** separate audio mute, counters, any operator-only view. |
| Person deflection / MediaPipe (PRD §9.3) | Not started. |
| `run.bat` (PRD #4) | Not started — macOS only today. |

### Announce gate (PRD §5.3) — implemented while wiring voice

`inference.stability_seconds` was configured but never used. It now gates
speech: a top-1 label must hold for 1.0 s before the robot says anything, so it
does not narrate every flicker while a child waves an object around.

Two behaviours worth knowing, both learned the hard way:

- **The gate re-requests on every stable frame, not only on label change.** The
  voice engine *drops* rather than defers anything inside its 2.5 s cooldown, so
  a speak-on-transition-only design would let an object go permanently unvoiced
  if its single transition happened to land in a cooldown window.
- **The attract barker is separately rate-limited** (`attract_interval_s: 60`).
  It re-fires every inference tick once the booth is idle, and the voice cooldown
  alone would have let it speak every ~2.5 s for three straight hours. Measured
  after the fix: **1 utterance per 100 s idle**, versus ~30 before.

### Booth-safety fixes made during the build

- **The stub classifier could have run the whole event undetected.** `_make_classifier()`
  fell back to `StubClassifier` on *any* exception with only a `log.warning`. The
  stub returns plausible random guesses with the identical schema, so a CLIP load
  failure on event day would have produced a booth that ran happily for three
  hours and was entirely fake. It now **refuses to start**, which surfaces the
  problem during the 12:00 setup window instead of mid-event. `FOOLBOT_ALLOW_STUB=1`
  is an explicit opt-in, and whenever the stub is active every WS frame carries
  `stub: true` and the UI shows an unmissable red **DEMO MODE — guesses are
  random, not real AI** banner. Both paths tested.
- **`/debug/capture` is gated behind `FOOLBOT_DEBUG=1`** (403 otherwise). It
  writes frames to disk, which PRD §6/§9.1 forbids at the booth as a hard
  architectural constraint. The kiosk launcher never sets the flag.

## Fixed this session

- **Calibration** — temperature 15 → 55 (see above).
- **Tuning sliders showed hardcoded HTML defaults and never synced from the
  server.** The panel displayed "Temperature 15 / floor 0.220" while the engine
  ran 55 / 0.240, which made a correct calibration read as broken. Sliders now
  mirror the live server config on every frame, and the server reports its config
  in every WS frame including idle. (Caveat: a slider keeps browser focus after a
  drag ends, and focused controls are skipped so we never yank one out from under
  the operator — so a slider that was nudged stays desynced until focus moves
  elsewhere. Harmless single-operator; only visible if tuning is changed from a
  second tab.)
- **Temperature slider `max` was 40** — T=55 was off the end of its own scale, so
  one accidental touch would silently clamp it and destroy the calibration. Range
  widened to 100; the sync code also widens the track if the live value ever sits
  outside it.
- **Config is now visible at all times**, including the idle state — the idle
  overlay (`inset:0; z-index:5`) used to bury the tuning panel.
- **Static assets are served `no-store`.** Chrome 304'd `style.css` and ran an old
  stylesheet against new markup, which read as "the fix didn't work". The UI gets
  edited live during setup; correctness beats caching here.

## Tooling added

- `GET /debug/capture?label=X&cls=clear|near-neighbor|out-of-vocab|empty&n=10&seconds=3`
  Saves the exact classified crop (pristine frame, no reticle) to `calib/`,
  appends ground truth to `calib/manifest.json`, and returns per-frame
  `raw_top_sim`, unsmoothed full-precision `top5`, `band`, `familiarity`,
  `edge_density`, `passes_presence` and the `tuning` in force — so a bad capture
  is visible immediately and every record is self-documenting.

  **Prefer this over reading the UI.** On-screen percentages are integer-rounded
  *and* EMA-smoothed by `Engine._smooth()`, while `raw_top_sim` passes through
  untouched — so a screenshot pairs a smoothed percentage with an unsmoothed
  similarity. A 6%-vs-5% reading can really be 6.4/4.6 or 5.5/5.4, a ~20×
  difference in the underlying similarity gap.

## Vocabulary expansion — 2026-07-26 (42 → 90 display labels)

Rationale: a child's own object had roughly even odds of falling outside the
original 42, which stalled throughput on "I have no idea" rather than producing a
teachable fool. Added 48: kid pocket items (fidget spinner, trading card, slime,
LEGO minifigure, bouncy ball, hair tie…), adult carry items (wallet, dollar bill,
credit card, car key, watch, earbuds, tablet…), and seven deliberate
near-neighbour confusers (coffee cup / travel mug vs mug; highlighter vs marker;
mitten vs glove; slipper and flip flop vs sandal; paper clip vs coin).

**Three consequences, all of them real:**

1. **Calibration invalidated** — see above. This is the blocking one.
2. **Voice cache more than doubled**: 1,161 utterances / 61,474 chars →
   **2,457 utterances / 132,264 chars**. That crosses the PRD's ~100k estimate,
   so confirm the ElevenLabs plan tier before generating. Label-bearing templates
   cost ×90 now; label-free ones are still ×1.
3. **The fool rate will drop**, because more of what children bring is now
   recognised. Target is 50–75% (PRD §7); below 50% the payoff never arrives.
   This is a metric to watch at the event, not a bug.

**Deliberately left out of vocabulary, to keep fooling reliable:** anything from
outdoors (rock, leaf, stick, pinecone, flower, shell, feather) — a coherent gap a
volunteer can remember and exploit — plus stapler and roll of tape, which are our
only measured out-of-vocab reference objects and would lose that role if added.
Note that **wallet was added at request**, so the wallet reading (0.259) in the
calibration doc is now a *historical in-vocab* figure, not an out-of-vocab one.

## NEXT STEPS (in order)

1. **One object-capture round — this unblocks three things at once.** With
   `FOOLBOT_DEBUG=1`, run `/debug/capture` over ~8 objects (a few clear in-vocab,
   the shoe near-neighbour pair, 2–3 out-of-vocab, one empty). That single round
   yields: real `anchor_margin` bounds so `familiarity_mode` can be switched to
   `anchor_margin`; the first real `manifest.json` for `scripts/calibrate.py`;
   and the missing object-in-zone `edge_density` value. Nothing else in the
   confidence core can be finished without it.
2. **Switch `familiarity_mode` to `anchor_margin`** once those bounds exist
   (open finding 1). The code is already in place and instrumented.
3. **Rewrite the `empty` scoring rule** in `calibrate.py` against `edge_density`
   or `anchor_margin` — `similarity_floor` is inert and cannot express it.
4. **Set a real ElevenLabs voice id** in a `voice:` block in `settings.yaml` and
   run `scripts/pregenerate_voice.py` (1161 utterances / 61k chars). The default
   voice id is a placeholder, and changing it invalidates the whole cache by
   design — so pick it before generating, not after. Confirm the plan tier first.
5. **Rest of the operator view** (PRD §5.7) — the arm gate (`O` / hold `Space`)
   covers the panic case. Still missing: a mute that silences audio without
   stopping the guessing (`voice.set_muted()` and `voice.status()` already exist
   and are surfaced in every WS frame — only a control is needed), and counters.
   Then fool detection / leaderboard / celebration.
6. **Give `config/challenges.yaml` a consumer** in the front end.
7. Kiosk-resolution layout check (open finding 3); `run.bat` for the Windows
   backup laptop.

### Loose ends worth knowing

- `inference.ema_window` is read into `Engine.__init__` and never used — only
  `ema_alpha` is live. Either implement it or drop the key.
  (`stability_seconds` is now live; see the announce gate above.)
- `config/labels.yaml`: `banana (toy)` was renamed to `toy banana`. The
  parenthesised form spoke as "A banana (toy)" in both `say` and ElevenLabs.
  The CLIP prompt is unchanged, so calibration is unaffected.
- The tuning panel is expanded by default on the child-facing screen. It is
  deliberately visible for now (it is how calibration is read), but it belongs
  behind the operator view before the event.
- `run.sh` does not use kiosk mode; it only passes
  `--autoplay-policy=no-user-gesture-required`. Use `Cmd+Ctrl+F` for fullscreen.

## Deadlines

- ~~**Mon Jul 27** — activity name + description to the Alive Center organizer~~
  **SENT** (2026-07-26).
- **Sat Aug 15, 12:00 PM** — setup; event 1–4 PM.
