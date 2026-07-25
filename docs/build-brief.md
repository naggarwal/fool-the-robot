# Build brief — "Fool the Robot" confidence-core prototype

Prototype to validate the two-number confidence design (PRD §4.2 + §5.2b) on
real objects before committing on Monday. Scope: **confidence concept only** —
camera → CLIP → calibrated confidence bars + familiarity meter, live in
browser, with live tuning sliders. Presentable fidelity. **No** voice, robot
face, challenge deck, leaderboard, face detection, or operator view.

Platform: macOS arm64 (Apple Silicon), Python 3.12, venv at `./.venv`.
Deps already installed: torch 2.13 (MPS available), open_clip 3.3, opencv 5.0,
fastapi, uvicorn, pyyaml, numpy, pillow.

## Directory layout & file ownership

```
config/labels.yaml      # DONE (scaffolded)
config/settings.yaml    # DONE (scaffolded)
foolbot/__init__.py     # DONE
foolbot/classifier.py   # AGENT A
foolbot/camera.py       # AGENT B
server.py               # AGENT B
static/index.html       # AGENT C
static/style.css        # AGENT C
static/app.js           # AGENT C
run.sh                  # DONE
```

Each agent writes ONLY its own files. Integration is the orchestrator's job.

## THE CONTRACT (all three agents build to this)

### 1. Classifier — `foolbot/classifier.py` (Agent A)

```python
class Classifier:
    def __init__(self, labels_path="config/labels.yaml",
                 settings_path="config/settings.yaml", device=None):
        # device: auto-pick "mps" if available else "cpu".
        # Load open_clip create_model_and_transforms(model.name, pretrained=model.pretrained).
        # Build text prompts for ALL labels (display + anchors) using
        #   settings.model.prompt_template.format(entry["prompt"]).
        # Encode ALL label texts ONCE here, L2-normalize, cache the matrix. NEVER
        #   re-encode text per frame. Only the image encoder runs in classify().

    def classify(self, frame_bgr) -> dict:
        # frame_bgr: HxWx3 uint8 BGR numpy array (OpenCV order).
        # Preprocess with the open_clip transform (convert BGR->RGB->PIL first),
        # encode image, L2-normalize, cosine-sim against cached label matrix.
        # Apply calibration:
        #   logits = cosine_sims * temperature      (NOT CLIP's built-in ~100 scale)
        #   probs  = softmax(logits) over ALL labels (display + anchors)
        # top5: the 5 highest-prob DISPLAY labels, as {"label", "pct"} (pct = prob*100),
        #       sorted desc. (Anchor probability is absorbed, never shown.)
        # raw_top_label / raw_top_sim: the DISPLAY label with the highest RAW cosine
        #       similarity, and that raw sim value.
        # familiarity: map raw_top_sim from [fam_low_sim..fam_high_sim] -> [0..100],
        #       clamped. (These are the same signal as the floor; see PRD §5.2b.)
        # band:
        #   "unknown"   if raw_top_sim < similarity_floor          (overrides all)
        #   "confident" elif top5[0].pct >= bands.confident_min
        #   "confused"  elif top5[0].pct <  bands.confused_max
        #   "hedging"   else
        return {
            "top5": [{"label": str, "pct": float}, ...],   # <=5, display labels only
            "familiarity": float,        # 0..100
            "band": str,                 # confident|hedging|confused|unknown
            "raw_top_sim": float,
            "raw_top_label": str,
            "temperature": float,        # current effective values (echo back)
            "floor": float,
            "fam_low_sim": float,
            "fam_high_sim": float,
        }

    def set_tuning(self, temperature=None, floor=None,
                   fam_low_sim=None, fam_high_sim=None,
                   confident_min=None, confused_max=None):
        # Live-update calibration params. Must NOT reload the model or re-encode text.
```

Also provide a `if __name__ == "__main__":` self-test that loads the model and
classifies a synthetic random image, printing the returned dict — so the piece
is runnable standalone without a camera.

### 2. Camera + server — `foolbot/camera.py` + `server.py` (Agent B)

`foolbot/camera.py`: a `Camera` class wrapping cv2.VideoCapture.
- Open `camera.index`; set width/height/fps from settings.
- Lock autofocus (`CAP_PROP_AUTOFOCUS`, 0) and exposure
  (`CAP_PROP_AUTO_EXPOSURE` = auto_exposure_value, `CAP_PROP_EXPOSURE` =
  exposure_value) when the respective lock flags are set. Wrap in try/except —
  many macOS UVC cams reject these; log a warning and continue, never crash.
- `read()` -> latest BGR frame (mirror horizontally if `camera.mirror`).
- `latest_jpeg()` -> JPEG bytes of the latest (already-mirrored) frame.
- A watchdog-friendly `reopen()` for stalled captures (basic is fine).

`server.py`: FastAPI `app`.
- `GET /health` -> `{"ok": true}` (used by run.sh readiness probe).
- `GET /` -> serve `static/index.html`.
- Mount `static/` at `/static`.
- `GET /video` -> MJPEG `multipart/x-mixed-replace; boundary=frame` stream of
  `latest_jpeg()` at ~15 fps. Frames are ALREADY mirrored — do not flip again.
- `WS /ws`:
  - On connect and continuously, push classification results (schema below) at
    most `inference.ws_push_hz` times/sec.
  - Inbound messages: `{"type":"tune", "temperature":.., "floor":.., "fam_low_sim":..,
    "fam_high_sim":.., "confident_min":.., "confused_max":..}` (any subset) ->
    call `classifier.set_tuning(...)`.
- Background capture/inference loop (asyncio task or thread):
  - Grab frames ~`camera.fps`; run `classifier.classify()` on every
    `inference.every_n_frames`th frame. Do inference OFF the event loop (thread /
    run_in_executor) so the MJPEG stream and WS stay responsive.
  - EMA-smooth the per-label pct across the last `ema_window` results
    (`ema_alpha` newest weight) before pushing, so bars don't jitter.
  - Presence: if `presence.enabled`, compute edge density (Canny mean) and if
    below `edge_density_min`, push `present: false` (UI shows idle) and skip/ða
    dim results.
  - Push over WS at `ws_push_hz`.
- Instantiate ONE `Classifier` at startup; import from `foolbot.classifier`.
  To develop/test standalone before Agent A lands, guard the import and fall
  back to a tiny inline `StubClassifier` returning plausible random results with
  the same schema, selected via env `FOOLBOT_STUB=1`.

**WebSocket server->client message schema (also given to Agent C):**
```json
{
  "type": "result",
  "present": true,
  "top5": [{"label": "banana", "pct": 78.3}, {"label": "corn cob", "pct": 11.2}],
  "familiarity": 84.0,
  "band": "confident",
  "raw_top_sim": 0.31,
  "raw_top_label": "banana",
  "temperature": 15.0,
  "floor": 0.22,
  "fam_low_sim": 0.20,
  "fam_high_sim": 0.30
}
```

### 3. Frontend — `static/{index.html,style.css,app.js}` (Agent C)

Single full-screen page, presentable, legible from a distance, booth-friendly
dark theme. Connects to `/video` (MJPEG `<img>`) and `/ws` (results).

Layout (PRD §4.2):
- Left ~55%: `<img src="/video">` live feed. Frames arrive already mirrored — do
  NOT apply CSS flip.
- Right ~45%, top: **primary guess** — top5[0].label at ≥72px, color-coded by band
  (confident=green, hedging=amber, confused=orange-red, unknown=purple). Show a
  short state caption ("Pretty sure!", "Hmm, not certain…", "No idea!").
- Right ~45%, middle: **confidence bars** — top5 as animated horizontal bars with
  %; percentages ≥36px. Smooth width transitions.
- Right ~45%, below bars: **familiarity meter** — a SEPARATE, differently-shaped
  gauge labeled "Does this look familiar to me?" driven by `familiarity` (0–100),
  with a HIGH/LOW readout. This must read as a different question from the bars,
  NOT a competing percentage. Always visible. (This is the whole point — see PRD.)
- A **tuning panel** (collapsible, visible by default): sliders for temperature
  (5–40), similarity floor (0.10–0.35), fam_low_sim (0.10–0.35), fam_high_sim
  (0.20–0.40), confident_min (50–90), confused_max (20–55). On input, send
  `{"type":"tune", ...}` over the WS. Also show the live raw_top_sim + raw_top_label
  as a small numeric readout (this is the "operator" number).
- When `present:false`, show a calm idle state ("Show me something!").

Reconnect the WS automatically if it drops. No build step, no bundler, vanilla JS.

## Calibration intent (so agents make sensible defaults)
A clear object in good light should read ~75–90% (not 99%). A near-neighbor pair
(sneaker vs boot) should land 40–60%. A novel/out-of-vocab object should fall
below the floor -> unknown + LOW familiarity. If your defaults make everything
read 99%, the temperature is too high — that's exactly the bug this prototype exists to expose and fix live.
