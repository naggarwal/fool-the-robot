"""FastAPI server for the Fool the Robot confidence-core prototype.

Responsibilities (see docs/build-brief.md §2):
  - GET /health           readiness probe
  - GET /                 serve static/index.html
  - /static               static asset mount
  - GET /video            MJPEG multipart stream of the (already-mirrored) feed
  - WS  /ws               push classification results at <= ws_push_hz; accept
                          inbound {"type":"tune", ...} messages
  - background capture + inference loop, EMA smoothing, Canny presence gate

Instantiates ONE Classifier from foolbot.classifier. If FOOLBOT_STUB=1 is set,
or that import fails, an inline StubClassifier with the identical schema is used
so the server runs standalone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from foolbot.camera import Camera, region_box

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("foolbot.server")

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "config" / "settings.yaml"
LABELS_PATH = BASE_DIR / "config" / "labels.yaml"
STATIC_DIR = BASE_DIR / "static"
CALIB_DIR = BASE_DIR / "calib"
MANIFEST_PATH = CALIB_DIR / "manifest.json"


def _load_yaml(path: Path) -> dict:
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


SETTINGS = _load_yaml(SETTINGS_PATH)


# ===========================================================================
# Stub classifier (schema-compatible fallback so the server runs standalone)
# ===========================================================================
class StubClassifier:
    """Returns plausible RANDOM results with the exact production schema."""

    def __init__(self, labels_path=LABELS_PATH, settings_path=SETTINGS_PATH, device=None):
        labels = _load_yaml(Path(labels_path))
        self._display_labels = [e["label"] for e in labels.get("display", [])]
        if not self._display_labels:
            self._display_labels = ["banana", "apple", "sneaker", "boot", "mug"]

        cal = _load_yaml(Path(settings_path)).get("calibration", {})
        bands = _load_yaml(Path(settings_path)).get("bands", {})
        self.temperature = float(cal.get("temperature", 15.0))
        self.floor = float(cal.get("similarity_floor", 0.22))
        self.fam_low_sim = float(cal.get("fam_low_sim", 0.20))
        self.fam_high_sim = float(cal.get("fam_high_sim", 0.30))
        self.confident_min = float(bands.get("confident_min", 70))
        self.confused_max = float(bands.get("confused_max", 40))
        log.info("StubClassifier active (%d display labels).", len(self._display_labels))

    def classify(self, frame_bgr) -> dict:
        # Pick a random handful of labels and hand out descending probability.
        k = min(5, len(self._display_labels))
        chosen = random.sample(self._display_labels, k)
        weights = sorted((random.random() ** 2 for _ in range(k)), reverse=True)
        total = sum(weights) + 1e-9
        # Leave some mass unassigned so top-1 rarely hits ~100%.
        scale = random.uniform(0.55, 0.95)
        top5 = [
            {"label": lbl, "pct": round(w / total * 100 * scale, 1)}
            for lbl, w in zip(chosen, weights)
        ]
        top5.sort(key=lambda d: d["pct"], reverse=True)

        raw_top_sim = round(random.uniform(0.12, 0.34), 3)
        raw_top_label = top5[0]["label"]

        fam = (raw_top_sim - self.fam_low_sim) / max(
            self.fam_high_sim - self.fam_low_sim, 1e-6
        )
        familiarity = round(max(0.0, min(1.0, fam)) * 100, 1)

        if raw_top_sim < self.floor:
            band = "unknown"
        elif top5[0]["pct"] >= self.confident_min:
            band = "confident"
        elif top5[0]["pct"] < self.confused_max:
            band = "confused"
        else:
            band = "hedging"

        return {
            "top5": top5,
            "familiarity": familiarity,
            "band": band,
            "raw_top_sim": raw_top_sim,
            "raw_top_label": raw_top_label,
            "temperature": self.temperature,
            "floor": self.floor,
            "fam_low_sim": self.fam_low_sim,
            "fam_high_sim": self.fam_high_sim,
        }

    def set_tuning(self, temperature=None, floor=None, fam_low_sim=None,
                   fam_high_sim=None, confident_min=None, confused_max=None):
        if temperature is not None:
            self.temperature = float(temperature)
        if floor is not None:
            self.floor = float(floor)
        if fam_low_sim is not None:
            self.fam_low_sim = float(fam_low_sim)
        if fam_high_sim is not None:
            self.fam_high_sim = float(fam_high_sim)
        if confident_min is not None:
            self.confident_min = float(confident_min)
        if confused_max is not None:
            self.confused_max = float(confused_max)


# Set when the booth is running on random numbers instead of CLIP. Surfaced in
# every WS frame so the UI can shout about it -- see _make_classifier.
USING_STUB = False
STUB_REASON = ""


def _make_classifier():
    """Real Classifier unless explicitly stubbed.

    This used to fall back to StubClassifier on ANY exception with only a
    log.warning. That is the worst possible behaviour for a live booth: the
    stub returns plausible random guesses with the identical schema, so a CLIP
    load failure on event day would produce a demo that runs happily for three
    hours and is entirely fake, with nothing on screen to give it away.

    Now it fails loudly at startup -- which surfaces during the 12:00 setup
    window rather than mid-event -- unless the operator opts in deliberately.
    """
    global USING_STUB, STUB_REASON
    if os.environ.get("FOOLBOT_STUB") == "1":
        log.warning("FOOLBOT_STUB=1 -> StubClassifier (RANDOM guesses, not CLIP).")
        USING_STUB, STUB_REASON = True, "FOOLBOT_STUB=1 set deliberately"
        return StubClassifier()
    try:
        from foolbot.classifier import Classifier

        return Classifier(
            labels_path=str(LABELS_PATH), settings_path=str(SETTINGS_PATH)
        )
    except Exception as exc:
        if os.environ.get("FOOLBOT_ALLOW_STUB") == "1":
            log.error(
                "Real Classifier unavailable (%s) -> DEGRADED to StubClassifier. "
                "Guesses are RANDOM. FOOLBOT_ALLOW_STUB=1 permitted this.", exc
            )
            USING_STUB, STUB_REASON = True, f"CLIP failed to load: {exc}"
            return StubClassifier()
        log.critical("Real Classifier failed to load: %s", exc)
        raise RuntimeError(
            f"CLIP classifier failed to load ({exc}). Refusing to start: the "
            f"fallback emits RANDOM guesses that look identical to real ones. "
            f"Fix the model load, or set FOOLBOT_ALLOW_STUB=1 to run a knowingly "
            f"fake booth (a red banner will be shown on screen)."
        ) from exc


# ===========================================================================
# Shared engine: capture thread + inference thread + latest result
# ===========================================================================
class Engine:
    def __init__(self, settings: dict, classifier, voice=None):
        self.settings = settings
        self.classifier = classifier
        self.voice = voice
        self.camera = Camera(settings)

        inf = settings.get("inference", {})
        self.fps = int(settings.get("camera", {}).get("fps", 30))
        self.every_n = max(1, int(inf.get("every_n_frames", 3)))
        self.ema_alpha = float(inf.get("ema_alpha", 0.5))
        self.ema_window = int(inf.get("ema_window", 5))
        self.ws_push_hz = float(inf.get("ws_push_hz", 10))

        pres = settings.get("presence", {})
        self.presence_enabled = bool(pres.get("enabled", True))
        self.edge_density_min = float(pres.get("edge_density_min", 0.02))

        region = settings.get("detection_region", {})
        self.region_enabled = bool(region.get("enabled", True))
        self.region = region

        self._lock = threading.Lock()
        self._result: dict | None = None
        self._present = True
        self._ema: dict[str, float] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        # --- announce gate (PRD 5.3) ---------------------------------------
        # stability_seconds was configured but never used. The robot must not
        # narrate every flicker while a child waves an object around, so a
        # top-1 label has to hold for this long before it is worth speaking.
        self.stability_seconds = float(inf.get("stability_seconds", 1.0))
        self.attract_after_s = float(inf.get("attract_after_s", 30.0))
        # Without this the barker re-fires every inference tick once the booth
        # is idle, and the voice cooldown alone would let it speak every ~2.5s
        # for three hours. It is a barker line, not a loop.
        self.attract_interval_s = float(inf.get("attract_interval_s", 60.0))
        self._last_attract_at: float = 0.0
        self._stable_label: str | None = None
        self._stable_since: float = 0.0
        self._last_present_at: float = time.time()
        self._spoken_text: str | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        t_cap = threading.Thread(target=self._capture_loop, daemon=True, name="capture")
        t_inf = threading.Thread(target=self._inference_loop, daemon=True, name="inference")
        self._threads = [t_cap, t_inf]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self.camera.release()

    # ----------------------------------------------------------------- loops
    def _capture_loop(self) -> None:
        period = 1.0 / max(self.fps, 1)
        fail_streak = 0
        while not self._stop.is_set():
            t0 = time.time()
            frame = self.camera.read()
            if frame is None:
                fail_streak += 1
                if fail_streak >= 30:
                    self.camera.reopen()
                    fail_streak = 0
            else:
                fail_streak = 0
            dt = time.time() - t0
            if dt < period:
                self._stop.wait(period - dt)

    def _inference_loop(self) -> None:
        # Sample roughly one frame per `every_n` captured frames.
        period = self.every_n / max(self.fps, 1)
        while not self._stop.is_set():
            t0 = time.time()
            frame = self.camera.latest_frame()
            if frame is not None:
                frame = self._crop_region(frame)
                present = self._check_presence(frame)
                if present:
                    try:
                        raw = self.classifier.classify(frame)
                        smoothed = self._smooth(raw)
                        with self._lock:
                            self._present = True
                            self._result = smoothed
                        self._last_present_at = time.time()
                        self._maybe_announce(smoothed)
                    except Exception as exc:
                        log.exception("classify() failed: %s", exc)
                else:
                    with self._lock:
                        self._present = False
                    self._stable_label = None
                    self._maybe_attract()
            dt = time.time() - t0
            if dt < period:
                self._stop.wait(period - dt)

    # --------------------------------------------------------------- voice
    def _maybe_announce(self, result: dict) -> None:
        """Speak the band once the top-1 label has held for stability_seconds.

        Re-requests on EVERY stable frame rather than only on change. The voice
        engine drops (does not defer) anything inside its cooldown, so a
        speak-on-transition-only design would let an object go permanently
        unvoiced if its one transition happened to land in a cooldown window.
        """
        if self.voice is None:
            return
        top5 = result.get("top5") or []
        if not top5:
            return
        label = top5[0]["label"]
        now = time.time()
        if label != self._stable_label:
            self._stable_label = label
            self._stable_since = now
            return
        if now - self._stable_since < self.stability_seconds:
            return
        try:
            spoken = self.voice.speak(result.get("band", "confused"), label)
        except Exception as exc:  # audio must never take the booth down
            log.warning("voice.speak failed: %s", exc)
            return
        if spoken:
            self._spoken_text = spoken

    def _maybe_attract(self) -> None:
        """Barker line at an empty booth. Lowest priority; anything outranks it."""
        if self.voice is None:
            return
        now = time.time()
        if now - self._last_present_at < self.attract_after_s:
            return
        if now - self._last_attract_at < self.attract_interval_s:
            return
        try:
            if self.voice.speak("attract"):
                self._last_attract_at = now
        except Exception as exc:
            log.warning("voice.speak(attract) failed: %s", exc)

    # --------------------------------------------------------------- region
    def _crop_region(self, frame: np.ndarray) -> np.ndarray:
        """Crop to the centered detection box, so CLIP sees the object zone
        rather than the whole scene. Matches the reticle drawn on the video."""
        if not self.region_enabled:
            return frame
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = region_box(w, h, self.region)
        crop = frame[y0:y1, x0:x1]
        return crop if crop.size else frame

    # ------------------------------------------------------------- presence
    def _check_presence(self, frame: np.ndarray) -> bool:
        if not self.presence_enabled:
            return True
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 160)
        density = float(np.count_nonzero(edges)) / edges.size
        return density >= self.edge_density_min

    # --------------------------------------------------------------- smoothing
    def _smooth(self, raw: dict) -> dict:
        """EMA-smooth per-label pct so the bars don't jitter. Labels present in
        the new result move toward their pct; absent labels decay toward 0."""
        a = self.ema_alpha
        current = {d["label"]: float(d["pct"]) for d in raw.get("top5", [])}
        # Update every tracked label; decay ones that dropped out.
        for lbl in list(self._ema.keys()):
            target = current.get(lbl, 0.0)
            self._ema[lbl] = a * target + (1 - a) * self._ema[lbl]
        for lbl, pct in current.items():
            if lbl not in self._ema:
                self._ema[lbl] = pct  # seed with first observation
        # Drop negligible labels to keep the dict small.
        self._ema = {k: v for k, v in self._ema.items() if v > 0.3}

        top5 = sorted(
            ({"label": k, "pct": round(v, 1)} for k, v in self._ema.items()),
            key=lambda d: d["pct"],
            reverse=True,
        )[:5]

        out = dict(raw)
        out["top5"] = top5
        return out

    # --------------------------------------------------------------- readers
    def snapshot(self) -> tuple[bool, dict | None]:
        with self._lock:
            return self._present, (dict(self._result) if self._result else None)

    def apply_tuning(self, payload: dict) -> None:
        keys = ("temperature", "floor", "fam_low_sim", "fam_high_sim",
                "confident_min", "confused_max")
        kwargs = {k: payload[k] for k in keys if k in payload and payload[k] is not None}
        if kwargs:
            self.classifier.set_tuning(**kwargs)


# ===========================================================================
# FastAPI app
# ===========================================================================
app = FastAPI(title="Fool the Robot")
engine: Engine | None = None
voice = None  # foolbot.voice.VoiceEngine | None


@app.on_event("startup")
def _startup() -> None:
    global engine, voice
    classifier = _make_classifier()
    # Audio is a nice-to-have: a silent booth still demonstrates the lesson,
    # so a voice failure must never stop the server from starting.
    try:
        from foolbot.voice import from_config

        voice = from_config().start()
        log.info("Voice engine started (%s).", voice.status().get("tier"))
    except Exception as exc:
        log.warning("Voice unavailable (%s) -> running silent.", exc)
        voice = None
    engine = Engine(SETTINGS, classifier, voice=voice)
    engine.start()
    log.info("Engine started.")


@app.on_event("shutdown")
def _shutdown() -> None:
    if engine is not None:
        engine.stop()
    if voice is not None:
        try:
            voice.shutdown()
        except Exception as exc:
            log.warning("voice.shutdown failed: %s", exc)


# static mount (dir may not exist yet while Agent C works — create-safe)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def _no_cache_static(request, call_next):
    """Never let the booth serve a stale style.css / app.js.

    Chrome 304'd style.css during calibration and silently ran an old
    stylesheet against new markup, which read as "the fix didn't work".
    The UI is edited live during setup, so correctness beats caching here.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/", response_model=None)
def index():
    idx = STATIC_DIR / "index.html"
    if idx.is_file():
        return FileResponse(str(idx))
    return JSONResponse(
        {"ok": True, "note": "static/index.html not present yet (Agent C)."}
    )


def _mjpeg_generator(target_fps: float = 15.0):
    boundary = b"--frame"
    period = 1.0 / target_fps
    while True:
        t0 = time.time()
        jpeg = engine.camera.latest_jpeg() if engine is not None else None
        if jpeg is not None:
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)


@app.get("/video")
def video() -> StreamingResponse:
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/debug/capture")
def debug_capture(
    label: str,
    cls: str = "clear",
    n: int = 10,
    seconds: float = 3.0,
) -> JSONResponse:
    """Capture a burst of N classified-region crops for offline calibration.

    Saves the EXACT crop the inference loop sees (pristine frame, no reticle)
    to calib/<label>__<i>.png and appends one manifest record per frame with
    the operator-supplied ground truth. Returns per-frame shape + raw_top_sim
    so a black/empty capture is visible immediately rather than at sweep time.

    cls is the scoring class used by scripts/calibrate.py:
      clear | near-neighbor | out-of-vocab | empty
    """
    # PRD §6 / §9.1: "No images are ever written to disk" is a hard architectural
    # constraint for the event. This endpoint exists only for pre-event
    # calibration and MUST be unreachable at the booth, so it is opt-in via an
    # env var that the kiosk launcher never sets.
    if os.environ.get("FOOLBOT_DEBUG") != "1":
        return JSONResponse(
            {"ok": False,
             "error": "disabled: /debug/capture writes frames to disk and is "
                      "off unless FOOLBOT_DEBUG=1 (see PRD 9.1)"},
            status_code=403,
        )
    if engine is None:
        return JSONResponse({"ok": False, "error": "engine not started"}, status_code=503)
    valid_cls = ("clear", "near-neighbor", "out-of-vocab", "empty")
    if cls not in valid_cls:
        return JSONResponse(
            {"ok": False, "error": f"cls must be one of {valid_cls}"}, status_code=400
        )

    CALIB_DIR.mkdir(exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")
    gap = max(seconds, 0.0) / max(n, 1)

    frames: list[dict] = []
    existing = len(list(CALIB_DIR.glob(f"{slug}__*.png")))
    for i in range(n):
        frame = engine.camera.latest_frame()
        if frame is None:
            frames.append({"i": i, "error": "no frame from camera"})
            time.sleep(gap)
            continue
        crop = engine._crop_region(frame)
        fname = f"{slug}__{existing + i:03d}.png"
        cv2.imwrite(str(CALIB_DIR / fname), crop)

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 160)
        rec: dict = {
            "file": fname,
            "true_label": label,
            "cls": cls,
            "shape": list(crop.shape),
            "mean_px": round(float(crop.mean()), 2),
            # presence gate inputs: a smooth, light object on a light wall can
            # fall under edge_density_min and be treated as an empty zone.
            "edge_density": round(float(np.count_nonzero(edges)) / edges.size, 5),
            "passes_presence": bool(
                float(np.count_nonzero(edges)) / edges.size >= engine.edge_density_min
            ),
        }
        try:
            res = engine.classifier.classify(crop)
            rec["raw_top_sim"] = round(float(res["raw_top_sim"]), 4)
            rec["raw_top_label"] = res["raw_top_label"]
            # anchor-margin instrumentation (calibration doc Finding 1) -- the
            # candidate replacement signal for out-of-vocab detection
            rec["raw_anchor_sim"] = round(float(res.get("raw_anchor_sim", 0.0)), 4)
            rec["anchor_margin"] = round(float(res.get("anchor_margin", 0.0)), 4)
            # unsmoothed, full-precision top5 -- NOT the EMA'd values the UI shows
            rec["top5"] = [{"label": d["label"], "pct": round(float(d["pct"]), 2)}
                           for d in res["top5"]]
            rec["band"] = res["band"]
            rec["familiarity"] = round(float(res["familiarity"]), 1)
            # tuning in force for this capture, so every record is self-documenting
            rec["tuning"] = {k: res[k] for k in
                             ("temperature", "floor", "fam_low_sim", "fam_high_sim")}
        except Exception as exc:  # pragma: no cover - debug path
            rec["error"] = f"classify failed: {exc}"
        frames.append(rec)
        time.sleep(gap)

    # Append to the manifest (read-modify-write; this endpoint is operator-driven
    # and single-user, so no locking beyond the GIL is warranted).
    manifest: list[dict] = []
    if MANIFEST_PATH.is_file():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text())
        except json.JSONDecodeError:
            log.warning("manifest.json unreadable; starting fresh")
    manifest.extend([f for f in frames if "file" in f])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    sims = [f["raw_top_sim"] for f in frames if "raw_top_sim" in f]
    return JSONResponse({
        "ok": bool(sims),
        "label": label,
        "cls": cls,
        "captured": len(sims),
        "raw_top_sim_range": [min(sims), max(sims)] if sims else None,
        "total_in_manifest": len(manifest),
        "frames": frames,
    })


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    push_period = 1.0 / max(engine.ws_push_hz if engine else 10, 1)

    async def receiver():
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "tune" and engine:
                    engine.apply_tuning(data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    recv_task = asyncio.create_task(receiver())
    try:
        while True:
            present, result = engine.snapshot() if engine else (False, None)
            if result is None:
                payload = {"type": "result", "present": bool(present), "top5": [],
                           "familiarity": 0.0, "band": "unknown"}
                # the operator panel must show the live config even with an
                # empty zone, so the numbers can never silently go stale
                clf = engine.classifier if engine else None
                if clf is not None:
                    payload.update({
                        "temperature": float(getattr(clf, "temperature", 0.0)),
                        "floor": float(getattr(clf, "floor", 0.0)),
                        "fam_low_sim": float(getattr(clf, "fam_low_sim", 0.0)),
                        "fam_high_sim": float(getattr(clf, "fam_high_sim", 0.0)),
                    })
            else:
                payload = {"type": "result", "present": bool(present), **result}
                if not present:
                    payload["top5"] = []
            # Caption the line the speaker ACTUALLY said (speak() returns the
            # text only when accepted), so the screen can never claim audio the
            # child never heard.
            if engine is not None:
                payload["spoken"] = engine._spoken_text
            if voice is not None:
                st = voice.status()
                payload["voice"] = {"tier": st.get("tier"), "muted": st.get("muted"),
                                    "speaking": st.get("speaking")}
            # A fake booth must never look like a real one.
            payload["stub"] = USING_STUB
            if USING_STUB:
                payload["stub_reason"] = STUB_REASON
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(push_period)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        recv_task.cancel()


if __name__ == "__main__":
    import uvicorn

    srv = SETTINGS.get("server", {})
    uvicorn.run(
        app,
        host=srv.get("host", "127.0.0.1"),
        port=int(srv.get("port", 8000)),
    )
