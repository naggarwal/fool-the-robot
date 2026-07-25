# PRD: "Can You Fool the Robot?"

**An interactive AI vision booth for Alive Center's 2026 STEM Exploration Day**

| | |
|---|---|
| **Owner** | Naveen Aggarwal, ExplAIned Consulting |
| **Event** | Alive Center 2026 STEM Exploration Day |
| **Date / Time** | Saturday, August 15, 2026, 1:00–4:00 PM (setup from 12:00 PM) |
| **Venue** | Alive Center, 500 W. 5th Ave., Naperville, IL |
| **Audience** | 200–300 attendees; elementary and middle school students (grades ~3–8) plus parents |
| **Build window** | ~3 weeks from July 25, 2026 |
| **Status** | Ready for implementation |

---

## 1. Summary

A booth station where a laptop and webcam run a live image classifier. A child holds an object up to the camera; the system displays its top guesses with confidence bars and **speaks its guess aloud in a robot persona**. The core loop is not "watch the AI be right" — it is **"try to make the AI wrong."**

Every session ends with the child understanding one idea: *AI is a very good guesser, not a know-it-all. It only knows what it was shown.*

The talking voice is the hook. Confidence bars are the lesson. The fool-it challenge is the engagement engine.

---

## 2. Why this exists

Alive Center is a teen-led youth nonprofit serving grades 5–12. ExplAIned Consulting is a sponsor and needs at least one interactive STEM activity appropriate for elementary and middle school students. Two 6-foot tables are provided; power and Wi-Fi are available on request.

A finished AI demo that silently works is a magic trick, not a lesson. Children watch, say "cool," and leave with the misconception reinforced that computers are infallible oracles. This project deliberately inverts that: the AI's **uncertainty and failure** are the product.

### Secondary goal

ExplAIned Consulting is an AI consultancy. Parents standing behind their children are the commercial audience. The mental model the booth teaches — *AI estimates, it does not know* — is the same first principle the business sells to SMB clients. The booth should feel professional and branded without being a sales pitch aimed at children.

---

## 3. Goals and non-goals

### Goals

1. A child aged 8–14 can operate the station with no adult help after a ten-second explanation.
2. A full interaction cycle completes in **90 seconds or less**, so throughput supports a line of families.
3. The AI **speaks** every guess aloud, in character, with expression that varies by confidence level.
4. Confidence is always visible and always the visual focus — never a bare answer.
5. At least one deliberate, reproducible "the AI got it wrong" moment is available on demand.
6. The station runs for **three continuous hours** without a crash, a restart, or an operator touching a terminal.
7. Runs fully offline if venue Wi-Fi fails, with degraded but working voice.

### Non-goals for v1

- Training a new model live (the "Teachable Machine" concept). Deferred to a documented phase 2.
- Any cloud vision inference. All image classification is local.
- Storing, uploading, transmitting, or recording any image of any attendee. Explicitly forbidden — see §9.
- Multi-station networking, accounts, or persistent user profiles.
- Mobile or tablet support. This is a fixed laptop station.

---

## 4. The experience

### 4.1 Interaction flow

**Attract mode (idle, no object detected)**
Full-screen animated robot face with an idle blink. Rotating prompt text: *"Show me something! I'll guess what it is."* Occasional spoken barker line every ~45 seconds to draw a crowd (*"Hello! Can anyone fool me today?"*). The leaderboard of objects that fooled the robot is visible in a side panel.

**Step 1 — The hook (0–10s)**
Child holds an object in front of the camera. The system detects a stable frame and locks a guess. Robot speaks: *"Ooh! I'm pretty sure that's a... banana!"* Confidence bars animate in. Child gets the satisfying "it worked" moment.

**Step 2 — The reveal (10–25s)**
The confidence panel is the visual centerpiece: a ranked list of the top five candidate labels with animated horizontal bars and percentages. The robot verbalizes its own uncertainty: *"I'm 84% sure. But I also thought it might be a corn cob."* This is where "the computer is guessing" lands.

**Step 3 — The challenge (25–75s)**
A challenge card appears on screen with one randomly drawn task from the challenge deck (§4.3), e.g. *"Turn it sideways. Can you still fool me?"* The child manipulates the object. The system re-classifies continuously. When top-1 confidence drops below the confusion threshold, the robot reacts audibly: *"Wait... what? Now I have no idea what that is!"*

**Step 4 — The lesson (75–90s)**
On a successful fool, a celebration state fires: confetti, a sound cue, and the object is added to the on-screen **"Objects That Fooled Me Today"** leaderboard. The robot delivers the teaching line: *"You got me! I only know what I've been shown before. I've never seen one like that."*

The staffer or teen volunteer asks the closing question: **"Why do you think it got confused?"** This is the highest-value moment of the entire activity and belongs in the runbook, not the software.

### 4.2 Screen layout

Single full-screen view on an external monitor, landscape, designed to be legible from six feet away by an adult and from three feet by a child.

- **Left ~55%:** live webcam feed, mirrored (so movement feels natural), with a subtle framing reticle showing the active detection region.
- **Right ~45%, top:** animated robot face that reacts to state — confident, uncertain, confused, delighted.
- **Right ~45%, middle:** confidence bar panel, top five labels, animated transitions, color-coded by confidence band. Directly beneath it, a **familiarity meter** (see below).
- **Right ~45%, bottom:** current challenge card.

**The two-number design — confidence bars *and* a familiarity meter.** The panel deliberately shows two visually distinct things that answer two different questions, because together they teach the full lesson:

- **Confidence bars** answer *"of the things I know, which one is it?"* — the relative softmax ranking of the top five labels, as percentages. This is the guess.
- **Familiarity meter** answers *"does this look like anything I know at all?"* — a single gauge derived from the **raw cosine similarity** of the top label (§5.2b), mapped through the calibrated floor onto a 0–100 "familiarity" scale. It is a meter, never a decimal or a competing percentage.

These are never shown as two competing percentages for the same object — that confuses rather than clarifies. The bars are a ranked list; the familiarity meter is a distinct gauge with its own label (e.g. *"Does this look familiar to me?"*). Both are always visible.

Why both: the confidence bars alone cannot show the single most important outcome. Shown a novel object outside the vocabulary, the bars *still* pick something — they must, softmax always sums to 100%. It is the familiarity meter dropping to LOW that makes "you fooled me" **visible** rather than only spoken, and that visibly distinguishes the two failure modes:

- Near-neighbor confusion (sneaker vs. boot): bars split ~55/45, familiarity still HIGH — *"I know it's footwear, I just can't tell which."*
- Truly novel object (a stapler): a bar may still read ~40%, but familiarity drops LOW — *"I have no idea what that is."*

The raw cosine similarity itself (the underlying number, ~0.15–0.35 range) is **never shown on the child-facing screen** — it is not a layperson-legible number and reads as a false low confidence. It appears only in the operator view (§5.7) for the parent who asks what the model is really doing.
- **Persistent bottom strip:** "Objects That Fooled Me Today" scrolling leaderboard with a running count.

Minimum type size for the primary guess: **72px**. Confidence percentages: **36px minimum**. Assume a bright, noisy room with people standing at angles.

### 4.3 The challenge deck

Randomized cards, each a single instruction, phrased for a child. Approximately fifteen cards, drawn without immediate repeat. Examples:

- Turn it upside down.
- Cover half of it with your hand.
- Show me only a tiny piece of it, very close up.
- Move it very far away.
- Show me a *drawing* of one instead of the real thing.
- Show me two of them at the same time.
- Show me something I have definitely never seen before.
- Put it in front of something colorful.
- Show it to me sideways.
- Make it blurry by moving it fast.

Each card should carry a one-line "why this works" note visible only in the operator view, so a teen volunteer can explain the mechanism when asked.

---

## 5. Technical architecture

### 5.1 Stack

Python backend with a local web UI, per owner decision.

- **Language:** Python 3.11+
- **Backend:** FastAPI with a WebSocket channel for pushing classification results to the UI
- **Camera + preprocessing:** OpenCV
- **Inference:** PyTorch, CPU-capable, GPU-accelerated if available
- **Frontend:** Single-page vanilla JS + HTML + CSS served by FastAPI. No build step. Avoid a bundler; a volunteer must never need `npm`.
- **Launch:** A single `run.sh` (and `run.bat`) that starts the server, waits for readiness, and opens Chrome in kiosk mode at `localhost`. **One double-click to go live.**

### 5.2 Model choice — important

**Do not use a plain ImageNet-1000 classifier.** ImageNet's label set contains roughly 120 dog breeds and a long tail of obscure categories, which produces outputs that are confusing to children, unfunny, and occasionally inappropriate when a person enters frame.

**Use CLIP zero-shot classification against a curated label set.**

- Model: `ViT-B/32` (via `open_clip` or Hugging Face `transformers`). Runs at roughly 5–15 FPS on a modern laptop CPU, comfortably real-time on any GPU.
- The label list is a **curated, config-driven vocabulary of ~60–100 kid-relevant objects**: hat, shoe, sneaker, water bottle, backpack, phone, banana, apple, stuffed animal, book, pencil, sunglasses, LEGO brick, soccer ball, key, coin, glove, umbrella, headphones, etc.
- Labels live in `config/labels.yaml` and are editable without touching code.

Why this matters:

1. The vocabulary is **content-safe by construction** — the model cannot output a label you did not authorize.
2. You control difficulty. You can deliberately include near-neighbor labels (sneaker vs. dress shoe vs. boot) to make confusion easy and instructive.
3. Adding a topical object the week of the event is a one-line config change.

### 5.2b Confidence calibration — read this before writing any inference code

**This is the single highest-risk technical decision in the build, and getting it wrong silently destroys the entire educational premise.**

Naive `softmax(logits_per_image)` on CLIP will not work. CLIP's learned `logit_scale` is ~100, which makes the softmax over a ~90-label set extremely peaked: top-1 lands at 95–99% on almost any input, including garbage. If implemented naively, the confidence panel shows one full bar and four empty ones every single time, the three confidence bands are never exercised, and fool-detection essentially never fires. The booth would demonstrate the exact opposite of its thesis.

Two required changes:

**A. Temperature calibration.** Do not use the built-in logit scale. Divide cosine similarities by a **tunable temperature in `settings.yaml`** (start around `0.01`–`0.05` scaled, i.e. an effective logit scale in the 10–25 range rather than 100) and calibrate empirically in week 3 against the actual prop set under booth lighting. **Calibration target:** a clearly-presented object in good conditions should read roughly 75–90%, not 99%; a near-neighbor pair (sneaker vs. boot) should land in the 40–60% band; an unknown object should fall below 40%. Ship a small `scripts/calibrate.py` that sweeps temperature against a labeled folder of test photos and reports the resulting band distribution, so this is tuned with data rather than vibes.

**B. An explicit "I don't know" path.** A closed vocabulary means CLIP is structurally incapable of expressing ignorance — shown a novel object, it returns a *confidently wrong* label rather than low confidence. This directly breaks the "show me something I've never seen" challenge card, which is one of the best cards in the deck. Two mechanisms, both required:

- **Anchor labels.** Add a set of ~10 distractor/rejection prompts to the label set that are never displayed as guesses (e.g. "a random object", "an unidentifiable thing", "a blurry photo", "a person's hand"). Probability mass landing on anchors is the model's implicit "none of the above." Mark these `display: false` in `labels.yaml`.
- **Absolute similarity floor.** Independent of the softmax, gate on the **raw cosine similarity** of the top label. Below a tuned floor, the system declares unknown regardless of relative ranking. This is what catches the truly novel object.

The same raw top-label similarity that drives this floor also drives the **familiarity meter** in the UI (§4.2). Map it onto a 0–100 display scale during week-3 calibration: the tuned unknown floor anchors the LOW end of the meter, and a clearly-recognized in-vocabulary object under good conditions anchors the HIGH end. `calibrate.py` should report the raw-similarity distribution across the test set so this mapping is set from data, not guessed. The meter and the floor are the same signal shown two ways — a novel object drops the meter to LOW *and* trips the unknown state together, by construction.

The **unknown state is a first-class UI and voice state**, not an error: *"Hmm. I have absolutely no idea what that is. You got me!"* It is, in fact, the single best outcome the booth can produce.

> **Note for the implementing agent:** the risk here is not "too accurate." It is **confidently wrong**. A robot that says "I'm 99% sure that's a banana" while looking at a stapler makes AI look broken and stupid, not fallible and interesting. Confidence numbers must be believable to a parent standing behind the child.

### 5.3 Classification loop

- **Text embeddings for the full label set are computed once at startup and cached in memory.** Never re-encode label prompts per frame; doing so alone would sink the frame rate. Only the image encoder runs in the loop.
- **Camera settings are locked at startup** via OpenCV: disable autofocus (`CAP_PROP_AUTOFOCUS`) and auto-exposure (`CAP_PROP_AUTO_EXPOSURE`), with fixed values in `settings.yaml`. Autofocus hunting as a child moves an object in and out of frame is a leading cause of classification jitter and will otherwise be misread as model instability.
- **Video reaches the browser over an MJPEG multipart endpoint**, not base64 frames over the WebSocket. The WebSocket carries classification results and state only. Base64 frames at 10 FPS filling a 1080p panel will compete with inference for CPU.
- Sample the camera at ~10 FPS; run inference on every Nth frame to hold CPU headroom.
- Apply **temporal smoothing**: an exponential moving average over the last ~5 inference results. Raw frame-by-frame CLIP output is jittery, and a label flickering between two values reads as broken rather than uncertain.
- **Stability gate:** only announce a new guess when the smoothed top-1 label has held for ~1.0 second. Prevents the robot from babbling continuously.
- **Confidence bands** (tunable in config, calibrated per §5.2b):
  - `>= 70%` — confident. Robot is bold.
  - `40–69%` — hedging. Robot expresses doubt.
  - `< 40%` — confused. Fires the "you fooled me" path.
  - **below the raw-similarity floor — unknown.** Distinct state, distinct voice lines, distinct robot face.
- **Fool detection:** a successful fool is registered when any of the following is sustained for ~1.5 seconds while an object is still present in frame: top-1 confidence falls below the confusion threshold; the top-2 labels are within ~8 percentage points of each other; or the unknown state triggers.
- **Presence detection:** a simple frame-difference or edge-density heuristic to distinguish "an object is being shown" from "empty background," so the system returns to attract mode cleanly. Do not rely on the classifier for this.

### 5.4 Voice system — the part most likely to fail

Owner selected cloud TTS. **A cloud dependency at a community-center event is the single highest-risk element of this build.** Venue Wi-Fi with 200–300 attendees on it is unreliable, and a mute robot is a dead booth. Therefore the voice system is specified as a **three-tier cascade, and all three tiers are mandatory deliverables.**

**Tier 1 — Pre-generated cache (primary in practice)**
Ship a build-time script, `scripts/pregenerate_voice.py`, that renders every possible utterance to local audio files before the event. At runtime, a cache hit plays instantly from disk with zero network dependency.

**For the cache to actually cover ~100% of utterances, spoken lines must be made finitely enumerable. This constrains the copy, and the constraint is mandatory:**

- **The robot never speaks a raw percentage.** Speaking "84%" would mean template × label × 101 values — an unbounded cache and a guaranteed live network call at the exact moment the demo lands. Instead the robot speaks the *band* in plain language: *"I'm pretty sure that's a banana"* / *"I think maybe it's a banana?"* / *"I have no idea what that is."* The precise percentage is shown **on screen**, where it belongs anyway — it is a thing to read and compare, not to listen to. This is a better design, not just a cheaper one.
- **The robot never speaks two labels in one line.** The hedging line becomes *"...but it might be something else"*, with the runner-up visible on screen. Otherwise the cache is label × label.
- Result: the cache is **templates × labels**, a few thousand files, fully enumerable and generated in advance.
- `pregenerate_voice.py` must be **incremental and hash-keyed** — skip any file whose (voice, model, text) hash already exists — because the phrase list and label list will be edited repeatedly during week 3 and a full re-render each time will burn quota.

**Budget note:** roughly 20 label-bearing templates × ~90 labels is on the order of 100k characters per full regeneration, which exceeds ElevenLabs' entry tier and consumes most of a mid-tier month. **Confirm the plan tier before week 2** and rely on incremental generation thereafter.

**Tier 2 — Live cloud TTS (cache miss)**
- Provider: **ElevenLabs, model `eleven_flash_v2_5`** (~75ms model latency, built for real-time). Use the streaming endpoint.
- Hard timeout: **1200ms**. On timeout, fall through to Tier 3 immediately and cache nothing.
- Any successful live generation is **written into the Tier 1 cache** so it is free and instant next time.
- API key from environment variable, never committed.

**Tier 3 — Offline local TTS (last resort)**
Sounds noticeably worse. Acceptable, because a robotic voice is on-theme and a working booth beats a beautiful silent one.

**Do not use `pyttsx3` in-process.** Its documented failure modes are precisely this workload: `run loop already started` errors on repeated `runAndWait()` calls, an `NSSpeechDriver` attribute crash on rapid successive macOS calls, blocking behavior hostile to an async server, per-thread `CoInitialize` requirements on Windows SAPI5, and no way to interrupt an utterance (which would silently violate the barge-in requirement).

Instead, **shell out to the OS one utterance per subprocess** — `say` on macOS, `System.Speech.Synthesis` via PowerShell on Windows. A subprocess can be killed for barge-in, and a wedged engine cannot take the server down with it.

**Audio playback (applies to all three tiers)**

Playback happens **in Python, not the browser.** Browser `<audio>` is disqualified: Chrome's autoplay policy blocks sound until a user gesture, so the attract-mode barker line — the thing meant to draw a crowd to an untouched kiosk — would never fire. (If browser playback is ever revisited, the launcher must pass `--autoplay-policy=no-user-gesture-required`.)

Use **`pygame.mixer`** for playback: it decodes MP3, and critically it can **stop mid-utterance**, which the barge-in requirement depends on. `playsound` cannot stop, `winsound` cannot play MP3, and `simpleaudio` is unmaintained — none satisfy the spec. Request **WAV** from ElevenLabs rather than MP3 if decode latency proves noticeable on the booth laptop.

**Voice design**
- Persona: friendly, curious, a little goofy. Never smug. Never condescending. When fooled, **delighted** rather than defeated — the child should feel rewarded, not like they broke something.
- Expression varies by confidence band. Confident lines are brisk; hedging lines are drawn out; confused lines are exclamatory.
- **Speech queue with barge-in:** never overlap utterances. A new higher-priority event (a successful fool) interrupts and replaces a queued low-priority line (a routine guess). Nothing is worse at a booth than a robot talking over itself.
- **Cooldown:** minimum ~2.5 seconds between utterances, so a child waving an object does not trigger a stream of chatter.
- Volume through a **small powered external speaker**, not laptop speakers. A gymnasium-style room with 300 people will swallow laptop audio entirely.

**Phrase templates** live in `config/phrases.yaml`, grouped by state (`attract`, `confident`, `hedging`, `confused`, `fooled`, `celebration`), with multiple variants per state selected at random to avoid repetition over a three-hour shift. Assume a child may stand at the booth for ten minutes and will notice repeats.

### 5.5 Configuration

Everything tunable lives in YAML, no code edits required on event day:

```
config/
  labels.yaml        # the object vocabulary
  phrases.yaml       # spoken line templates by state
  challenges.yaml    # the challenge deck + operator "why" notes
  settings.yaml      # thresholds, timings, camera index, voice IDs
```

### 5.6 Physical setup — the camera must not point at faces

The default setup — a laptop-lid or monitor-clipped webcam — points squarely at children's faces and the queue behind them. That puts the person-deflection path (§9.3) in permanent conflict with the demo and makes a backdrop impossible.

**Required arrangement:**

- Webcam on a **gooseneck or short tripod, aimed down and forward at a marked object zone on the table** — a taped rectangle or a printed mat the child places the object on or holds above. The child's face is out of frame by geometry, not by software.
- A **neutral matte backdrop card** behind and beneath the object zone, so the model sees the object rather than a moving crowd.
- **Working distance is fixed at roughly 30–45 cm** from lens to object zone, and all thresholds in §5.2b are calibrated at that distance. Record the value used in `settings.yaml`.
- A **clip-on LED fill light** aimed at the zone, to make classification independent of overhead venue lighting.
- The external monitor faces the child; the laptop screen faces the operator.

### 5.7 Operator view

A hidden panel toggled by a key combination (e.g. `Ctrl+Shift+O`), showing FPS, current inference latency, TTS tier currently in use, camera status, and a manual "reset to attract mode" button. Also a **panic key** that mutes audio instantly. Volunteers need a way to recover without a terminal.

The operator view is also where the **raw cosine similarity numbers** live — the actual top-label similarity, the current floor value, and the raw scores behind the familiarity meter (§4.2). These are deliberately kept off the child-facing screen but shown here for the parent who asks what the model is really doing (§2, the commercial audience). This is the panel a volunteer turns to the parent, not the child.

---

## 6. Data model

Minimal, ephemeral, local-only.

**Session record** (in memory, discarded on shutdown): timestamp, label guessed, top-5 confidences, whether a fool was registered, which challenge card was drawn.

**Leaderboard** (`data/leaderboard.json`, local disk only): object label, fool count, first-fooled timestamp. Persisted only so a mid-event crash does not lose the day's leaderboard.

**What the leaderboard actually records — this needs care.** A successful fool means the system *does not know what the object is*, so writing the current (wrong) top-1 label would produce a board listing objects nobody ever showed. Rule: **capture the last stable, confident label from before the fool began** (the object as first recognized in Step 1) and record the fool against that. For the unknown-object case, where there was never a confident label, the operator view offers a **one-tap picker** so a volunteer can name it in two seconds, defaulting to a generic "something new" entry if skipped. Never attempt to capture the image.

**No images are ever written to disk.** Frames exist in memory for the duration of inference and are discarded. This is a hard architectural constraint, not a preference.

---

## 7. Success metrics

Measured by the operator, informally, at the booth.

- **Throughput:** 60+ distinct children engage across three hours.
- **Dwell time:** median 60–120 seconds per child. Under 30 seconds means the hook is not landing; over 4 minutes means the line will stall.
- **Fool rate:** 50–75% of children successfully fool the robot. Below 50% and the challenges are too hard, so the payoff never arrives; above 85% and the AI looks broken rather than fallible.
- **Comprehension (the real metric):** when the staffer asks "why did it get confused?", the child articulates something resembling *"because it never saw one like that."* Target: a clear majority of children aged 8+.
- **Uptime:** zero unrecovered crashes across the three-hour window.
- **Parent conversations:** 15+ substantive adult conversations. This is the commercial metric.

---

## 8. Build plan

Three weeks. Sequenced so that a working booth exists at the end of week one and everything after is improvement, not risk.

**Week 1 — Core loop, end to end**
Camera capture → CLIP zero-shot against the curated vocabulary → smoothed, gated top-5 → basic full-screen UI with confidence bars → Tier 3 offline voice only. Goal: **a crude but complete working booth.** From this point forward the event is covered no matter what.

**Week 2 — Make it good**
Voice cascade (Tiers 1 and 2, plus the pre-generation script). Robot face and state animations. Challenge deck. Fool detection and celebration state. Leaderboard. Operator view and panic key.

**Week 3 — Harden and rehearse**
**Confidence calibration against the real prop set under booth lighting via `calibrate.py` — this is the make-or-break task of the whole build, not a polish item.** Three-hour soak test, unattended, checking for memory leaks and camera handle loss. Person-deflection tested with a real queue standing behind the table. Full offline rehearsal with Wi-Fi disabled and the API key removed. Kiosk launcher and one-page runbook. **Test with actual children** — ideally Alive Center teens, which also flatters the host organization and fits its teen-led model.

### Hard deadlines

- **Monday, July 27** — activity name and 1–3 sentence description due to the Alive Center organizer for the printed event guide. This is a writing deadline, not a build deadline, but it is the nearest one.
- **Week of August 8** — vendor layout map arrives; confirm power needs.
- **Saturday, August 15, 12:00 PM** — setup begins. Arrive no later than 12:30 PM.

---

## 9. Safety, privacy, and content constraints

Non-negotiable. This is a children's event and the camera is pointed at the public.

1. **No image is stored, transmitted, or logged.** Frames live in RAM only. No cloud vision API is used. State this on booth signage in plain language: *"This camera doesn't record. Nothing is saved. Nothing is uploaded."*
2. **The vocabulary is curated and bounded.** The model cannot emit a label outside `labels.yaml`. This structurally prevents the system from labeling a child's body, appearance, or clothing in any way that could embarrass or offend.
3. **Person handling.** If a face dominates the frame, the system must **not** attempt to classify it. The robot deflects in character: *"Hey, that's a person! I only guess about objects."*

   **Implementation is specified, because the default approaches fail at a crowded booth.** Use a **MediaPipe face detector** (or the OpenCV DNN SSD face model) — not a Haar cascade, which false-positives constantly under booth lighting. Deflection triggers only when a detected face exceeds a **frame-area threshold** (tunable, start ~15%) inside the active detection region. Faces in the background — the line of children waiting behind the presenter — must be **ignored**, or the booth deflects continuously and never demonstrates anything. Hands and forearms holding an object are normal and expected; do not treat them as persons. This interacts directly with camera placement (§5.7) and must be tested with a real queue standing behind the table.
4. **No personal data collected.** No names, no email capture from children, no sign-ups at the station. Parent lead capture, if any, is a separate paper or QR mechanism handled by a human and never mixed into the child's interaction.
5. **Audio content** is drawn only from the reviewed `phrases.yaml`. No generative text at runtime. Every line the robot can possibly say is written and reviewed in advance.
6. **Failure is framed positively.** Copy review pass: no line may make a child feel foolish, wrong, or bad at the task.

---

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Venue Wi-Fi fails or is saturated | Voice dies — booth is dead | Three-tier voice cascade; pre-generated cache covers ~95% of lines; full offline rehearsal is a week-3 deliverable |
| Room audio too loud to hear robot | Core hook lost | Powered external speaker, tested at volume; all spoken lines also render as on-screen text |
| Harsh or mixed venue lighting wrecks accuracy | AI seems broken, not fallible | Threshold tuning under realistic light; a clip-on LED fill light on the table; a neutral matte backdrop card behind the camera's active region |
| Laptop thermal throttling over 3 hours | FPS collapse mid-event | Soak test; inference frame-skipping; laptop on a stand with airflow, not flat on a tablecloth |
| Line forms, dwell time too long | Families walk away | Second table runs an unplugged backup activity; challenge cards are single-instruction by design; staffer manages flow |
| Children arrive empty-handed, or bring objects outside the vocabulary | Confident wrong answers read as broken; throughput stalls | Curated prop basket drawn directly from `labels.yaml` (§11) |
| Model is *too* accurate — kids can't fool it | The lesson never lands | Include near-neighbor labels in the vocabulary; the "show me a drawing" and "extreme close-up" cards reliably break CLIP |
| CLIP softmax too peaked; every guess reads 99% | Confidence lesson dies; fool-detection never fires | Temperature calibration + raw-similarity floor + anchor labels, per §5.2b; `calibrate.py` run against real props in week 3 |
| Novel object produces a *confidently wrong* label | AI looks broken and stupid rather than fallible | Explicit unknown state with its own voice lines and robot face; similarity floor independent of ranking |
| TTS process wedges or hangs mid-event | Silent robot, possibly hung server | One-shot killable subprocess per utterance; watchdog timeout; panic key; all lines also render on screen |
| Single point of failure: one laptop | Total loss | Second laptop with the identical repo, pre-installed and tested, sitting under the table |
| Camera handle lost on USB glitch | Silent freeze | Watchdog that detects a stalled frame source and re-opens the capture device automatically |

---

## 11. Deliverables

1. Python repo, runnable via one script on Windows and macOS, with pinned dependencies.
2. `config/` directory with all four YAML files populated and documented.
3. `scripts/pregenerate_voice.py` and a committed voice cache.
4. Kiosk launcher (`run.sh` / `run.bat`).
5. **One-page operator runbook** — setup steps, the ten-second pitch script, the three questions to ask each child, panic key, and a troubleshooting table. Written for a teen volunteer who has never seen the system.
6. Booth signage copy: the privacy notice and the "Objects That Fooled Me Today" header.
7. `README.md` covering local setup, config reference, and threshold tuning.
8. `scripts/calibrate.py` — temperature sweep against a labeled folder of test photos, reporting the resulting confidence-band distribution.
9. **A physical prop basket.** Not software, but the activity does not work without it. Roughly 25–30 objects drawn directly from `labels.yaml`, including: the deliberate near-neighbor sets (sneaker / dress shoe / boot), the printed drawing-and-photo cards the challenge deck assumes exist, and several objects *outside* the vocabulary to reliably trigger the unknown state. Many children arrive empty-handed and a child's own object has roughly even odds of falling outside the vocabulary. Include disinfectant wipes — these are shared objects handled by hundreds of children.

---

## 12. Phase 2 (documented, not built)

**"Teach Me Something New."** A second mode where a child shows the camera five examples of an object the robot does not know, the system computes and stores a CLIP embedding centroid for that new class, and the robot can then recognize it. This closes the loop perfectly: the child has just *felt* the limitation in v1, so fixing it themselves is the natural next beat. Explicitly out of scope for August 15 given the three-week window, but the v1 architecture should not preclude it — keep the label vocabulary and the embedding comparison layer decoupled so a user-defined class can be appended at runtime.

---

## Appendix A — Draft submission for the Alive Center event guide

Due to the Alive Center organizer by Monday, July 27.

**Activity name:** Can You Fool the Robot?

**Description:** Meet an AI that looks through a camera, guesses what you're holding, and says its answer out loud — along with how sure it is. Then comes the challenge: can you trick it? Kids turn objects sideways, hide them, and show it things it's never seen before to discover that AI doesn't really "know" anything — it's just a very good guesser that only understands what it's been shown.

---

**Sources consulted:** [ElevenLabs Models documentation](https://elevenlabs.io/docs/overview/models), [Alive Center](https://www.alivecenter.org/)
