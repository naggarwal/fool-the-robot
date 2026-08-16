# Can You Fool the Robot?

An interactive AI vision booth for the Alive Center's 2026 STEM Exploration Day
(Saturday, August 15, 1:00–4:00 PM, Naperville IL).

A child holds an object up to a webcam. A local CLIP model guesses what it is
and shows two things at once: **which** object it thinks it's looking at, and
**how familiar** that thing looks at all. Then the child tries to break it.

The lesson is one sentence: *AI is a very good guesser, not a know-it-all. It
only knows what it was shown.*

The booth ran at the event on **Saturday, 15 August 2026**, and it worked. This
repo is the archived record of it: everything needed to stand the booth back up
is committed here, and nothing else is. The machine it was built on has been
wiped.

Full product spec: [`PRD-fool-the-robot.md`](PRD-fool-the-robot.md).
Build state as of the event: [`docs/STATUS.md`](docs/STATUS.md).
Operator instructions for event day: [`docs/runbook.md`](docs/runbook.md).

---

## Reinstalling from scratch

Start from nothing — a Mac with no clone, no venv, no model weights:

```bash
brew install python@3.12          # skip if you already have it
git clone https://github.com/naggarwal/fool-the-robot.git
cd fool-the-robot
./setup.sh
```

Allow twenty minutes and about 1.7 GB of download. `setup.sh` builds `.venv`
from `requirements-lock.txt`, pulls the CLIP weights (~700 MB) into the local
Hugging Face cache so the booth never needs the network again, and then proves
the machine works rather than assuming it: model loads, `classify()` returns
guesses, a camera yields a frame, the real server starts and answers `/health`.
It ends with either **"This laptop is ready to run the booth"** or a list of
what is wrong. Then `./run.sh`.

Everything that mattered is in the clone — `server.py`, `foolbot/`, `static/`,
the full 90-label vocabulary and calibrated thresholds in `config/`, the
runbook, and the signage and checklists in `deliverables/`.

Four things deliberately are **not**, and none of them block a rebuild:

- **The venv and the CLIP weights.** ~1.6 GB of pure download. `setup.sh`
  fetches both; that is its whole job.
- **The pre-generated voice cache.** Regenerate with
  `./.venv/bin/python scripts/pregenerate_voice.py`, or skip it — without the
  cache the robot speaks through the macOS system voice, which is fine.
- **Calibration capture frames.** Webcam stills of one room under one set of
  lights; they do not transfer to another room. The *measurements* taken from
  them are kept: per-frame numbers in
  `calib/archive-2026-07-26/manifest.json`, and the reasoning that produced the
  shipped thresholds in
  [`docs/calibration-2026-07-26.md`](docs/calibration-2026-07-26.md).
  Top-level `calib/manifest.json` is `[]` — an empty slate for the next round.
- **UI screenshots.** Documentation only, and they show the room they were
  taken in.

The one thing a rebuild genuinely needs a human for is **recalibration**. The
thresholds in `config/settings.yaml` (temperature 55, the similarity floor) were
measured on one webcam in one room. On different hardware or in different light,
re-run a capture round with real objects in hand:

```bash
FOOLBOT_DEBUG=1 ./run.sh
./.venv/bin/python scripts/capture_round.py
```

[`docs/second-laptop.md`](docs/second-laptop.md) walks through the whole
build-a-fresh-booth path, recalibration included, and
[`docs/calibration-2026-07-26.md`](docs/calibration-2026-07-26.md) records how
the shipped numbers were arrived at.

---

## What is built today

This repo currently contains the **confidence core**: camera → CLIP zero-shot →
calibrated confidence bars → familiarity gauge, live in a browser, with tuning
sliders. Calibration against real objects is complete (temperature 55).

Wired in alongside it: `foolbot/voice.py` (three-tier speech engine) speaking
the lines in `config/phrases.yaml`, and the animated robot face.
`scripts/calibrate.py` (the temperature sweep) and `scripts/capture_round.py`
run standalone, outside the request path.

There is an **arm gate**: `O` (or the on-screen button) switches the robot off
and on, and holding `Space` while it is off buys one look for as long as the key
is down. Disarmed, the engine does not classify, speak, or run the attract line;
the camera keeps running so switching back on is instant. The gate lives on the
server and is echoed in every WS frame, so the screen shows what the engine is
actually doing rather than what the last keypress asked for.

Not built at all, all specified in the PRD: on-screen challenge cards, fool
detection, celebration, leaderboard, face detection and person deflection, the
rest of the operator view, `run.bat`.

`config/challenges.yaml` exists as a data file but **nothing reads it yet**.
Until the front end consumes it, challenge cards are run off paper or off the
operator's laptop.

`docs/STATUS.md` is the authority on what's live at any given moment; this
section is a snapshot.

---

## Requirements

- macOS on Apple Silicon (developed on an M5 MacBook Pro; an M1 is the tested
  backup). Apple's MPS backend is used automatically when available, CPU
  otherwise.
- Python 3.12
- A USB webcam
- ~350 MB of disk for the CLIP ViT-B/32 weights, downloaded once on first run
  and cached locally. After that the booth is fully offline.

## Setup

```bash
./setup.sh
```

Builds the venv from `requirements-lock.txt`, pre-downloads the CLIP weights so
event day needs no network, and then verifies the machine rather than assuming
it: model loads, `classify()` returns guesses, a camera yields a real frame, and
the server actually starts and answers `/health`. It ends with either "ready to
run the booth" or a list of what is wrong.

`./setup.sh --verify` re-runs those checks without reinstalling — the fastest
answer to "is this laptop ready?". `--fresh` rebuilds the venv from scratch.

For a **second (backup) laptop**, follow `docs/second-laptop.md` — same script,
plus what does not come across in a clone (calibration, camera index, voice).

By hand, if you prefer:

```bash
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements-lock.txt
```

`requirements.txt` states intent (`torch>=2.2`, …); `requirements-lock.txt` is
the exact set from the calibrated laptop, and is what `setup.sh` installs — a
backup that resolves to different versions than the machine the thresholds were
measured on is not a backup.

First launch takes about 7 seconds while CLIP loads. Subsequent launches are
instant.

## Run

```bash
./run.sh
```

That starts uvicorn on `127.0.0.1:8000`, polls `/health` until the server is
ready, then opens Google Chrome at the booth page. It passes
`--autoplay-policy=no-user-gesture-required` so that browser audio will be
possible when the voice tier lands. It does **not** launch Chrome in kiosk
mode — press `Cmd+Ctrl+F` for fullscreen once the page is up.

Stop with `Ctrl+C` in the launching terminal, or from anywhere:

```bash
./stop.sh
```

`stop.sh` targets whatever is listening on the port rather than matching a
process name, so it cannot hit an unrelated Python process. It sends `TERM`,
waits six seconds, then `KILL`s survivors, and exits non-zero if the port is
somehow still held.

Only one instance can hold the webcam at a time. Always stop the old one before
starting a new one.

`PORT` overrides the port for both scripts: `PORT=8080 ./run.sh`,
`PORT=8080 ./stop.sh`.

> The `/ws` push loop only ends when the browser disconnects, so uvicorn's
> default graceful shutdown would wait forever on an open booth tab — `Ctrl+C`
> appeared to hang and closing the terminal left an orphan holding the port.
> Both entry points now pass a 3-second `timeout-graceful-shutdown`, and
> `run.sh` traps `INT TERM HUP` (not just `EXIT`) and escalates to `KILL`.

### Environment variables

| Variable | Effect |
|---|---|
| `FOOLBOT_DEBUG=1` | Enables `GET /debug/capture`. Off by default. |
| `FOOLBOT_STUB=1` | Swaps the real classifier for `StubClassifier`, which returns plausible random results with the identical schema. Useful for front-end work with no camera and no model load. |
| `PORT` | Server port for `run.sh` (default 8000). |

`run.sh` sets neither `FOOLBOT_DEBUG` nor `FOOLBOT_STUB`, so the booth launcher
always runs the real classifier with disk writes disabled.

---

## Privacy: why `/debug/capture` is gated

**No image is ever written to disk at the booth.** Frames live in memory for the
duration of inference and are discarded. This is an architectural constraint
(PRD §9.1), not a preference, and it is what the booth signage promises parents.

`GET /debug/capture` is the one code path that writes frames to disk. It exists
only for pre-event calibration: it saves the exact classified crop to `calib/`
along with ground truth in `calib/manifest.json`, so thresholds can be set from
measurements rather than from screenshots. It returns HTTP 403 unless
`FOOLBOT_DEBUG=1` is set in the server's environment, and the kiosk launcher
never sets it.

`calib/*.png` is gitignored — those frames contain whoever ran the calibration
pass. `calib/manifest.json` (numbers and ground truth only) is kept.

---

## Architecture in brief

```
webcam ──► Camera (OpenCV, focus + exposure locked)
             │  capture thread @ camera.fps
             ├──► latest_jpeg() ──► GET /video   (MJPEG multipart, ~15 fps)
             └──► latest_frame()
                       │  inference thread, every Nth frame
                       ├─ crop to detection_region (centred box)
                       ├─ Canny presence gate (edge density)
                       ├─ Classifier.classify()   CLIP ViT-B/32
                       ├─ EMA smoothing of per-label percentages
                       └──► WS /ws  ──► static/app.js  ──► bars + gauge
```

- **`server.py`** — FastAPI. Serves `/`, `/static`, `/health`, `/video` (MJPEG),
  `/ws` (results out, tuning messages in), `/debug/capture` (gated). Owns the
  `Engine`: two daemon threads (capture, inference), the presence gate, the EMA,
  and the shared latest-result snapshot.
- **`foolbot/classifier.py`** — loads CLIP once, encodes **all** label prompts
  once at startup and caches the matrix. Only the image encoder runs per frame.
  Applies the calibrated temperature, produces top-5 display labels, the raw
  top similarity, the familiarity value and the band.
- **`foolbot/camera.py`** — capture device, autofocus/auto-exposure lock,
  mirroring, reticle drawing, JPEG encoding, and reopen-on-stall.
- **`static/`** — vanilla HTML/CSS/JS, no build step. A volunteer must never
  need `npm`.

Video goes over MJPEG rather than base64-over-WebSocket on purpose; the
WebSocket carries results and state only.

### Two numbers, not one

The screen shows two visually distinct things that answer two different
questions, and the distinction is the whole lesson:

- **Confidence bars** — *"of the things I know, which one is it?"* A softmax
  over every label, including the hidden anchors, scaled by the calibrated
  temperature. Relative, always sums toward 100%, and will always pick
  something.
- **Familiarity gauge** — *"does this look like anything I know at all?"* The
  raw cosine similarity of the best display label, mapped through
  `fam_low_sim`→`fam_high_sim` onto 0–100. Absolute. This is the signal that
  makes "you fooled me" visible rather than merely spoken.

The raw cosine similarity itself is never presented as a percentage on the
child-facing screen. It appears in the tuning panel readout for the operator.

---

## Configuration

Everything tunable lives in YAML. No code edits on event day.

| File | Contents | Status |
|---|---|---|
| `config/settings.yaml` | Thresholds, calibration, camera, detection region, inference loop, presence gate, server host/port | Calibrated 2026-07-26 |
| `config/labels.yaml` | The object vocabulary: 90 display labels + 10 hidden anchor labels | In use |
| `config/challenges.yaml` | The challenge deck and the operator-only "why this works" notes | Written; **no consumer yet** |
| `config/phrases.yaml` | Spoken line templates by state. Copy rules (one `{label}` per line, no digits, no `%`) are validated by `foolbot.voice.load_phrases()`, which raises on any violation | Written; consumed by `foolbot/voice.py`, which the server does not call yet |

### `labels.yaml`

Two sections. `display:` entries are shown as guesses; `anchors:` entries never
are. Each entry supplies a `prompt`, which is rendered through
`model.prompt_template` (`"a photo of {}"`) before encoding.

The vocabulary is curated on purpose. It is content-safe by construction — the
model cannot emit a label you did not authorise, which is what structurally
prevents it from ever labelling a child's body or clothing. It also contains
deliberate near-neighbour sets (sneaker / dress shoe / boot / sandal, and the
ball family) so that instructive confusion is easy to produce.

Anchor labels ("a random object", "a blurry photo", "a person's hand") are the
model's implicit "none of the above." Probability landing there is absorbed and
never displayed, which keeps confidently-wrong answers down. Note that anchors
currently affect the **bars only** — the familiarity gauge is driven by absolute
similarity and does not consult them.

Editing either list requires a server restart; text embeddings are computed once
at startup.

### `challenges.yaml`

One card per entry. `card:` is the only text a child ever sees. `why:` is
operator-only. `reliability:` records whether the card has actually been
measured on this build — most are honestly marked `untested`. Full schema is
documented at the top of the file.

### `settings.yaml` — the knobs that matter

```yaml
calibration:
  temperature: 55.0        # effective logit scale applied before softmax
  similarity_floor: 0.24   # below this raw sim -> "unknown", overrides bands
  fam_low_sim: 0.24        # raw sim that reads 0 on the gauge
  fam_high_sim: 0.33       # raw sim that reads 100 on the gauge
bands:
  confident_min: 70        # >= 70% -> confident
  confused_max: 40         # <  40% -> confused; in between -> hedging
```

---

## Threshold tuning

Read `docs/calibration-2026-07-26.md` before changing any of these. It records
the method and the measurements the current values came from.

`scripts/calibrate.py` re-runs the sweep numerically over the crops captured in
`calib/manifest.json`, which is the repeatable version of that pass. Use it
rather than reading percentages off the screen whenever the vocabulary, the
lens or the lighting changes.

### Temperature — the make-or-break knob

CLIP's built-in logit scale is about 100, which makes the softmax over a
52-label set so peaked that everything reads 95–99% including garbage. That
single default would destroy the entire premise of the booth: one full bar and
four empty ones on every input, forever. So the cosine similarities are divided
by a tunable temperature instead.

Targets, from PRD §5.2b: a clearly-presented object in good light should read
roughly **75–90%**, a near-neighbour pair should land in the **40–60%** band, and
an unfamiliar object should fall below 40%.

| Temperature | Behaviour |
|---|---|
| ≤ 45 | Near-neighbour pairs stuck under 30%; the robot reads as permanently confused |
| **50–65** | Satisfies both targets at once. **55 is the shipped midpoint.** |
| ≥ 70 | Confident-wrong territory: 95–99% on anything clear |

Measured at T=55: a coffee mug reads 74% `confident` with HIGH familiarity; the
shoe family splits 6/5/4/4; a roll of tape (not in the vocabulary) gives two
near-tied guesses plus LOW familiarity.

If clear objects read low across the board, raise temperature toward 60. If
everything reads 95%+, lower it. Change it in steps of 5, not 20.

### Similarity floor and the familiarity gauge

`similarity_floor` is deliberately set **low** (0.24) and is not what detects
unfamiliar objects. Measured in-vocabulary similarities run 0.274–0.332 and
out-of-vocabulary run 0.259–0.270 — the bands very nearly touch, and any floor
high enough to reject a wallet would also reject a real pen. The familiarity
gauge carries the "I've never seen that" signal instead, and its range was
widened to 0.24→0.33 to spread the observed values across the full dial.

Absolute similarity has a known hole, documented in the calibration record: an
**empty room measures 0.273**, which rates as more familiar than a roll of tape
and level with a pen. Absolute cosine similarity therefore cannot tell "a real
object I don't know" apart from "nothing at all." The anchor margin separates
the same frames by sign rather than degree (empty room −0.050, real objects
positive), which is why `anchor_margin` is the recommended fix rather than a
speculative one.

`fam_low_sim` is pinned equal to `similarity_floor` so the band and the gauge can
never contradict each other on screen.

`familiarity_mode` selects which signal drives the gauge. `absolute` (in use)
uses the raw top display similarity. `anchor_margin` is the designed fix for the
thin out-of-vocabulary margin: best display similarity minus best anchor
similarity, which is self-normalising per image in a way absolute similarity is
not. **Do not switch modes until `fam_margin_low` / `fam_margin_high` have been
set from real measurements** — they are placeholders.

### Bands

`confident_min` (70) and `confused_max` (40) split the top-1 percentage into
confident / hedging / confused. A raw similarity under the floor overrides all
three with `unknown`.

### Presence gate

`presence.edge_density_min` (0.02) decides whether anything is in the zone at
all, using Canny edge density rather than the classifier. Smooth pale objects on
a pale background sit close to this line; a routine scene measured 0.0158.
`/debug/capture` reports `edge_density` and `passes_presence` per frame, so set
this from one pale-object capture and one genuinely-empty capture rather than by
guessing.

### Live sliders — read this before using them

The tuning panel on the booth page pushes changes over the WebSocket straight
into the running classifier. **Nothing is written back to YAML.** Slider changes
are lost on restart, and a restart is the fastest way to recover a calibration
someone nudged by accident. Once a value is settled, copy it into
`settings.yaml` by hand.

One quirk: a slider that still has browser focus after a drag is skipped by the
sync-from-server logic, so it can display a stale value until focus moves
elsewhere. Harmless with one operator.

### A gotcha worth knowing

`Engine._smooth()` EMA-smooths the per-label **percentages** only.
`raw_top_sim` passes through untouched. A screenshot therefore pairs a smoothed
percentage with an unsmoothed similarity, and a "6% vs 5%" reading can really be
6.4/4.6 or 5.5/5.4 — about a 20× difference in the underlying gap. Prefer
`/debug/capture` over reading the UI whenever a number matters.

Note also that `inference.stability_seconds` and `inference.ema_window` are
loaded but not currently referenced by any code path; only `ema_alpha` is
active.

---

## Repo layout

```
vision/
  PRD-fool-the-robot.md      full product spec
  README.md                  this file
  run.sh                     one-command launcher
  requirements.txt           pinned-ish dependencies
  server.py                  FastAPI app + capture/inference engine
  config/
    settings.yaml            thresholds, camera, calibration
    labels.yaml              90 display labels + 10 anchors
    challenges.yaml          the challenge deck (+ operator notes)
    phrases.yaml             every line the robot can say, by state
  foolbot/
    classifier.py            CLIP load, calibrated classify(), set_tuning()
    camera.py                capture, focus/exposure lock, reticle, region_box
    voice.py                 three-tier speech engine (not wired into server yet)
  scripts/
    calibrate.py             temperature sweep over calib/manifest.json
  static/
    index.html  style.css  app.js
  calib/                     calibration crops (gitignored) + manifest.json
  docs/
    STATUS.md                current build state — read this first
    build-brief.md           the interface contract the build agents worked to
    calibration-2026-07-26.md  full calibration record and method
    runbook.md               one-page operator runbook for event day
    signage.md               printed booth signage copy
```

## Booth setup

Physical arrangement matters as much as the code, and is specified in PRD §5.6:
the webcam sits on a gooseneck or short tripod aimed **down at a marked object
zone on the table**, not at the child. Faces stay out of frame by geometry
rather than by software. Working distance is 30–45 cm, a matte backdrop card
sits behind and beneath the zone, and a clip-on LED fill light makes
classification independent of venue lighting. All thresholds above were
calibrated at that distance.
