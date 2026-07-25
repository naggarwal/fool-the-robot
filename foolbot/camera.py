"""Camera wrapper around cv2.VideoCapture for the Fool the Robot prototype.

Owns a single UVC / built-in webcam. Reads mirrored BGR frames, caches the
latest frame + a JPEG encoding of it, and locks autofocus / exposure where the
hardware allows (many macOS UVC cams reject these controls — we swallow the
error and keep going rather than crash).
"""

from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

log = logging.getLogger("foolbot.camera")


def region_box(width: int, height: int, region: dict) -> tuple[int, int, int, int]:
    """Centered detection box as (x0, y0, x1, y1) pixels for a WxH frame.

    Shared by the camera (to draw the reticle) and the server (to crop
    inference) so the drawn box and the classified region are always identical.
    """
    wf = float(region.get("width_frac", 0.6))
    hf = float(region.get("height_frac", 0.8))
    bw = int(round(width * wf))
    bh = int(round(height * hf))
    x0 = (width - bw) // 2
    y0 = (height - bh) // 2
    return x0, y0, x0 + bw, y0 + bh


def _placeholder_frame(width: int, height: int, text: str = "NO CAMERA") -> np.ndarray:
    """Solid dark frame with a label, used when the camera can't be opened."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (30, 30, 30)
    cv2.putText(
        frame,
        text,
        (int(width * 0.08), int(height * 0.5)),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (80, 80, 200),
        3,
        cv2.LINE_AA,
    )
    return frame


class Camera:
    """Thread-safe-ish wrapper: one writer (capture loop) via read(), many
    readers via latest_jpeg()/latest_frame()."""

    def __init__(self, settings: dict):
        cam = settings.get("camera", {})
        self.index = int(cam.get("index", 0))
        self.width = int(cam.get("width", 1280))
        self.height = int(cam.get("height", 720))
        self.fps = int(cam.get("fps", 30))
        self.mirror = bool(cam.get("mirror", True))

        self.lock_autofocus = bool(cam.get("lock_autofocus", False))
        self.autofocus_value = cam.get("autofocus_value", 0)
        self.lock_exposure = bool(cam.get("lock_exposure", False))
        self.auto_exposure_value = cam.get("auto_exposure_value", 0.25)
        self.exposure_value = cam.get("exposure_value", -6)

        self.jpeg_quality = int(cam.get("jpeg_quality", 80))

        region = settings.get("detection_region", {})
        self.draw_region = bool(region.get("enabled", True))
        self.region = region

        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_jpeg: bytes | None = None
        self.opened = False

        self._open()

    # ------------------------------------------------------------------ open
    def _open(self) -> None:
        try:
            cap = cv2.VideoCapture(self.index)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("VideoCapture(%s) raised: %s", self.index, exc)
            cap = None

        if cap is None or not cap.isOpened():
            log.warning(
                "Could not open camera index %s — running with placeholder frames.",
                self.index,
            )
            self.opened = False
            self._cap = None
            # Seed a placeholder so latest_jpeg() always has something.
            self._store(_placeholder_frame(self.width, self.height))
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)

        self._apply_focus_exposure(cap)

        self._cap = cap
        self.opened = True
        log.info(
            "Camera %s opened (%sx%s @ %sfps, mirror=%s).",
            self.index,
            self.width,
            self.height,
            self.fps,
            self.mirror,
        )

    def _apply_focus_exposure(self, cap: cv2.VideoCapture) -> None:
        """Best-effort focus/exposure lock. Never raises."""
        if self.lock_autofocus:
            try:
                cap.set(cv2.CAP_PROP_AUTOFOCUS, float(self.autofocus_value))
            except Exception as exc:
                log.warning("Autofocus lock unsupported on this camera: %s", exc)

        if self.lock_exposure:
            try:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, float(self.auto_exposure_value))
                cap.set(cv2.CAP_PROP_EXPOSURE, float(self.exposure_value))
            except Exception as exc:
                log.warning("Exposure lock unsupported on this camera: %s", exc)

    # ------------------------------------------------------------------ read
    def read(self) -> np.ndarray | None:
        """Grab one frame, mirror it if configured, cache it, and return it.

        Returns the mirrored BGR frame, or None if the grab failed (a
        placeholder is still cached so latest_jpeg() keeps working)."""
        if self._cap is None:
            # No camera: keep serving the placeholder.
            return self._latest_frame

        ok, frame = self._cap.read()
        if not ok or frame is None:
            log.debug("Frame grab failed.")
            return None

        if self.mirror:
            frame = cv2.flip(frame, 1)

        self._store(frame)
        return frame

    def _store(self, frame: np.ndarray) -> None:
        # latest_frame stays PRISTINE (the server crops it for inference);
        # the JPEG shown to the child gets the reticle drawn on a copy.
        disp = self._with_reticle(frame) if self.draw_region else frame
        ok, buf = cv2.imencode(
            ".jpg", disp, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        )
        with self._lock:
            self._latest_frame = frame
            if ok:
                self._latest_jpeg = buf.tobytes()

    def _with_reticle(self, frame: np.ndarray) -> np.ndarray:
        """Return a copy with the detection box drawn as corner brackets."""
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = region_box(w, h, self.region)
        out = frame.copy()
        color = (120, 230, 120)  # BGR — soft green
        t = max(2, int(w * 0.003))
        seg = int(min(x1 - x0, y1 - y0) * 0.12)  # corner bracket length
        for (cx, cy, dx, dy) in (
            (x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)
        ):
            cv2.line(out, (cx, cy), (cx + dx * seg, cy), color, t, cv2.LINE_AA)
            cv2.line(out, (cx, cy), (cx, cy + dy * seg), color, t, cv2.LINE_AA)
        return out

    # --------------------------------------------------------------- readers
    def latest_frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def latest_jpeg(self) -> bytes | None:
        """JPEG bytes of the latest (already-mirrored) frame, or None."""
        with self._lock:
            return self._latest_jpeg

    # -------------------------------------------------------------- watchdog
    def reopen(self) -> None:
        """Release and re-open the capture device (for stalled captures)."""
        log.info("Reopening camera %s ...", self.index)
        self.release()
        self._open()

    def release(self) -> None:
        cap, self._cap = self._cap, None
        self.opened = False
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
