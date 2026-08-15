#!/usr/bin/env python3
"""Prove a fresh laptop can actually run the booth. Run by setup.sh, and safe
to run any time (it is the fastest "is this machine ready?" answer there is).

Checks, in the order that matters:

  1. Python and platform are what the wheels were built for.
  2. CLIP loads and classifies. This downloads the weights on first run, which
     is the point -- event day should need no network.
  3. A camera exists and yields a REAL frame.

Every check that can fail quietly is made to fail loudly instead, because both
of this booth's silent failure modes look like a working booth:

  - StubClassifier returns plausible random guesses with the identical schema.
  - Camera falls back to a "NO CAMERA" placeholder frame rather than erroring.

Exit code is 0 only if the booth would genuinely work.
"""
from __future__ import annotations

import contextlib
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "
failures: list[str] = []
warnings: list[str] = []


def line(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def fail(msg: str) -> None:
    failures.append(msg)
    line(BAD, msg)


def warn(msg: str) -> None:
    warnings.append(msg)
    line(WARN, msg)


@contextlib.contextmanager
def quiet_stderr():
    """Silence C-level stderr for the duration of the block.

    Probing past the last camera makes AVFoundation print "out device of bound"
    and "camera failed to properly initialize" straight to fd 2 -- beneath
    Python, so OPENCV_LOG_LEVEL does not touch it. On a script whose entire job
    is to say whether the booth is healthy, scary text next to an [ ok ] line
    is worse than useless. Scoped to the probe only; nothing else is hidden.
    """
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        sys.stderr.flush()
        os.dup2(devnull, 2)
        yield
    finally:
        sys.stderr.flush()
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


# --------------------------------------------------------------- 1. platform
def check_platform() -> None:
    print("\n--- 1. Platform -------------------------------------------------")
    v = sys.version_info
    line(OK, f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    if (v.major, v.minor) != (3, 12):
        warn(f"Expected Python 3.12; this is {v.major}.{v.minor}. "
             "The locked wheels were built for 3.12.")
    line(OK, f"{platform.system()} {platform.release()} / {platform.machine()}")
    if platform.system() != "Darwin":
        warn("Not macOS -- run.sh/stop.sh are bash + macOS only.")
    elif platform.machine() != "arm64":
        warn("Not Apple Silicon -- requirements-lock.txt was frozen on arm64.")


# ------------------------------------------------------------------ 2. CLIP
def check_clip() -> None:
    print("\n--- 2. CLIP model -----------------------------------------------")
    print("      First run downloads ~700 MB of weights. Later runs are instant.")
    try:
        import torch  # noqa: F401
        line(OK, f"torch {torch.__version__}")
    except Exception as exc:
        fail(f"torch will not import: {exc}")
        return

    # Load through the SAME path the server uses. A preflight that loads the
    # model its own way can pass while the server still fails.
    try:
        from foolbot.classifier import Classifier
    except Exception as exc:
        fail(f"foolbot.classifier will not import: {exc}")
        return

    t0 = time.time()
    try:
        clf = Classifier(
            labels_path=str(ROOT / "config" / "labels.yaml"),
            settings_path=str(ROOT / "config" / "settings.yaml"),
        )
    except Exception as exc:
        fail(f"CLIP failed to load: {exc}")
        print("\n      If this is a download failure, check the network and "
              "re-run.\n      The server REFUSES to start in this state, by "
              "design -- the\n      fallback emits random guesses that look "
              "real.")
        return
    line(OK, f"CLIP loaded in {time.time() - t0:.1f}s")

    # Classify something. Loading is not proof of working.
    try:
        import numpy as np
        frame = np.full((720, 1280, 3), 128, dtype=np.uint8)
        result = clf.classify(frame)
        top5 = result.get("top5") or []
        if not top5:
            fail("classify() returned no guesses.")
            return
        top = ", ".join(f"{d['label']} {d['pct']:.0f}%" for d in top5[:3])
        line(OK, f"classify() works -- on a blank grey frame: {top}")
    except Exception as exc:
        fail(f"classify() raised: {exc}")


# ---------------------------------------------------------------- 3. camera
def check_camera() -> None:
    print("\n--- 3. Camera ---------------------------------------------------")
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        fail(f"opencv will not import: {exc}")
        return

    try:
        import yaml
        settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
        configured = int(settings.get("camera", {}).get("index", 0))
    except Exception:
        configured = 0

    # Probe directly rather than through foolbot.camera.Camera: that wrapper
    # deliberately degrades to a placeholder frame so the booth stays up, which
    # is right at runtime and useless for answering "is there a camera?".
    working: list[int] = []
    misses = 0
    for idx in range(4):
        if misses >= 2:
            break          # two dead indexes in a row means the list ended
        cap = None
        try:
            with quiet_stderr():
                cap = cv2.VideoCapture(idx)
                opened = cap.isOpened()
                ok, frame = cap.read() if opened else (False, None)
            if not opened:
                misses += 1
                continue
            misses = 0
            if not ok or frame is None:
                continue
            # An all-identical frame is a lens cap or a dead virtual device.
            if float(np.std(frame)) < 1.0:
                warn(f"index {idx}: opens but the picture is blank "
                     "(lens cap? virtual camera?)")
                continue
            h, w = frame.shape[:2]
            line(OK, f"index {idx}: {w}x{h}, live picture")
            working.append(idx)
        except Exception:
            continue
        finally:
            if cap is not None:
                cap.release()

    if not working:
        fail("No working camera found on indexes 0-3. "
             "Check the USB webcam, and macOS camera permission for Terminal.")
        return
    if configured not in working:
        fail(f"config/settings.yaml uses camera index {configured}, which does "
             f"not work here. Working: {working}. Set camera.index to one of "
             f"those.")
    else:
        line(OK, f"config/settings.yaml camera.index = {configured} -- matches")
    if len(working) > 1:
        print(f"      More than one camera ({working}). On a laptop the "
              "built-in\n      one is usually 0 -- the booth wants the USB "
              "webcam aimed at the table.")


def main() -> int:
    print("=" * 68)
    print("Fool the Robot -- preflight")
    print("=" * 68)
    check_platform()
    check_clip()
    check_camera()

    print("\n" + "=" * 68)
    if failures:
        print(f"NOT READY -- {len(failures)} problem(s):")
        for f in failures:
            print(f"  - {f}")
        print("=" * 68)
        return 1
    if warnings:
        print(f"Ready, with {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("Ready. Model loads, classifies, and the camera works.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
