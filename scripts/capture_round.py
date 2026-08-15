#!/usr/bin/env python3
"""Walk an operator through one /debug/capture round for calibration.

Prompts for each object in turn, fires the capture, and immediately checks the
result so a bad take is caught while the object is still in your hand rather
than at sweep time. Requires the server running with FOOLBOT_DEBUG=1.

    ./.venv/bin/python scripts/capture_round.py

Keys at each prompt: Enter = capture, r = redo last, s = skip, q = quit.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
N = 10
SECONDS = 3.0

# cls drives scoring in scripts/calibrate.py. Every class must be populated or
# the sweep has nothing to score for it and can settle on a degenerate corner.
PLAN = [
    ("mug",           "clear",        "a plain coffee mug, handle visible"),
    ("scissors",      "clear",        "open them slightly so the blades read"),
    ("water bottle",  "clear",        "label side toward the camera"),
    ("sneaker",       "near-neighbor", "side-on, laces visible"),
    ("dress shoe",    "near-neighbor", "side-on, same distance as the sneaker"),
    ("stapler",       "out-of-vocab", "NOT in the 90 labels - reserved fooler"),
    ("roll of tape",  "out-of-vocab", "NOT in the 90 labels - reserved fooler"),
    ("rock",          "out-of-vocab", "any outdoor item: rock, leaf or pinecone"),
    ("empty-room",    "empty",        "step back, clear the zone entirely"),
]


def capture(label: str, cls: str) -> dict:
    q = urllib.parse.urlencode(
        {"label": label, "cls": cls, "n": N, "seconds": SECONDS}
    )
    with urllib.request.urlopen(f"{BASE}/debug/capture?{q}", timeout=60) as r:
        return json.loads(r.read())


def report(res: dict) -> bool:
    """Print a verdict. Returns True if the take looks usable."""
    if not res.get("ok"):
        print(f"  !! capture failed: {res.get('error', res)}")
        return False
    frames = [f for f in res["frames"] if "raw_top_sim" in f]
    lo, hi = res["raw_top_sim_range"]
    dens = [f["edge_density"] for f in frames]
    passes = sum(1 for f in frames if f["passes_presence"])
    tops = {f["raw_top_label"] for f in frames}
    margins = [f["anchor_margin"] for f in frames]

    print(f"  captured {res['captured']}/{N}   sim {lo:.4f}-{hi:.4f}")
    print(f"  edge_density {min(dens):.5f}-{max(dens):.5f}   "
          f"presence {passes}/{len(frames)}")
    print(f"  anchor_margin {min(margins):+.4f}..{max(margins):+.4f}")
    print(f"  guesses: {', '.join(sorted(tops))}")

    ok = True
    if res["cls"] != "empty" and passes < len(frames):
        print("  !! object did not fill the zone on every frame - move closer "
              "and REDO (r)")
        ok = False
    if res["cls"] == "empty" and passes:
        print("  !! zone is NOT empty on some frames - clear it and REDO (r)")
        ok = False
    if max(dens) == 0.0 and res["cls"] != "empty":
        print("  !! zero edges: black or blank capture - REDO (r)")
        ok = False
    return ok


def main() -> int:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=5) as r:
            json.loads(r.read())
    except Exception as exc:
        print(f"server not reachable at {BASE}: {exc}")
        print("start it with: FOOLBOT_DEBUG=1 ./.venv/bin/python -m uvicorn "
              "server:app --host 127.0.0.1 --port 8000")
        return 1

    print(f"Capture round: {len(PLAN)} objects x {N} frames over {SECONDS}s each.")
    print("Watch the booth window and keep the object inside the white box.\n")

    i = 0
    while i < len(PLAN):
        label, cls, hint = PLAN[i]
        print(f"[{i + 1}/{len(PLAN)}] {label}  ({cls})")
        print(f"      {hint}")
        try:
            key = input("      Enter=capture  s=skip  q=quit > ").strip().lower()
        except EOFError:
            return 1
        if key == "q":
            print("stopped early.")
            return 0
        if key == "s":
            i += 1
            print()
            continue

        print("      capturing, hold steady...")
        try:
            res = capture(label, cls)
        except Exception as exc:
            print(f"  !! request failed: {exc}")
            continue
        good = report(res)
        if not good:
            try:
                again = input("      r=redo  Enter=accept anyway > ").strip().lower()
            except EOFError:
                return 1
            if again == "r":
                print()
                continue
        i += 1
        print()

    print("Round complete. calib/manifest.json is written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
