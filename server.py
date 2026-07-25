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


def _make_classifier():
    """Real Classifier unless FOOLBOT_STUB=1 or the import/init fails."""
    if os.environ.get("FOOLBOT_STUB") == "1":
        log.info("FOOLBOT_STUB=1 -> using StubClassifier.")
        return StubClassifier()
    try:
        from foolbot.classifier import Classifier

        return Classifier(
            labels_path=str(LABELS_PATH), settings_path=str(SETTINGS_PATH)
        )
    except Exception as exc:
        log.warning("Real Classifier unavailable (%s) -> StubClassifier.", exc)
        return StubClassifier()


# ===========================================================================
# Shared engine: capture thread + inference thread + latest result
# ===========================================================================
class Engine:
    def __init__(self, settings: dict, classifier):
        self.settings = settings
        self.classifier = classifier
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
                    except Exception as exc:
                        log.exception("classify() failed: %s", exc)
                else:
                    with self._lock:
                        self._present = False
            dt = time.time() - t0
            if dt < period:
                self._stop.wait(period - dt)

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


@app.on_event("startup")
def _startup() -> None:
    global engine
    classifier = _make_classifier()
    engine = Engine(SETTINGS, classifier)
    engine.start()
    log.info("Engine started.")


@app.on_event("shutdown")
def _shutdown() -> None:
    if engine is not None:
        engine.stop()


# static mount (dir may not exist yet while Agent C works — create-safe)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
            else:
                payload = {"type": "result", "present": bool(present), **result}
                if not present:
                    payload["top5"] = []
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
