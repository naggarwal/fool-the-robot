#!/usr/bin/env bash
# One-command setup for a second (backup) booth laptop. Apple Silicon macOS.
#
# Run this AT HOME, with wifi. It builds the virtualenv, downloads the CLIP
# weights so event day needs no network, and then proves the booth actually
# works rather than assuming it does.
#
#     ./setup.sh            build (or top up) the venv, then verify
#     ./setup.sh --fresh    delete .venv first and rebuild from scratch
#     ./setup.sh --verify   skip installing; just run the checks
#
# It does NOT calibrate. Thresholds are camera- and room-specific and belong to
# a human with real objects in hand -- see docs/second-laptop.md.
set -uo pipefail
cd "$(dirname "$0")"

FRESH=0
VERIFY_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --fresh)  FRESH=1 ;;
    --verify) VERIFY_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

PY=./.venv/bin/python
PORT="${PORT:-8000}"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
died() { printf '\n\033[31mSTOPPED: %s\033[0m\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------- 0. preflight
say "Checking this machine..."

[ "$(uname -s)" = "Darwin" ] || died "This script is macOS only (found $(uname -s)).
run.sh and stop.sh are bash scripts written for macOS. A Windows booth needs
run.bat/stop.bat, which do not exist yet."

if [ "$(uname -m)" != "arm64" ]; then
  echo "  ! Not Apple Silicon (found $(uname -m)). requirements-lock.txt was"
  echo "    frozen on arm64; the install may pull different wheels."
fi
echo "  macOS $(sw_vers -productVersion) on $(uname -m)"

# Tell the operator what to run rather than installing Python for them: this
# touches the system toolchain, and a surprise Homebrew install on a laptop
# that is meant to be a known-good backup is exactly the wrong move.
if ! command -v python3.12 >/dev/null 2>&1; then
  died "python3.12 not found.

Install it, then re-run this script:

    brew install python@3.12

(If you do not have Homebrew: https://brew.sh)"
fi
echo "  $(python3.12 -V) at $(command -v python3.12)"

for f in requirements-lock.txt config/settings.yaml config/labels.yaml server.py; do
  [ -f "$f" ] || died "Missing $f -- is this a complete clone of the repo?"
done
echo "  Repo files present"

# ------------------------------------------------------------------- 1. venv
if [ "$VERIFY_ONLY" -eq 0 ]; then
  if [ "$FRESH" -eq 1 ] && [ -d .venv ]; then
    say "Removing the existing .venv (--fresh)..."
    rm -rf .venv
  fi

  if [ -d .venv ]; then
    say "Reusing the existing .venv (pass --fresh to rebuild)..."
  else
    say "Creating .venv..."
    python3.12 -m venv .venv || died "Could not create the virtualenv."
  fi

  say "Installing dependencies (a few minutes -- torch is large)..."
  "$PY" -m pip install --quiet --upgrade pip || died "Could not upgrade pip."
  # The LOCK file, not requirements.txt: a backup laptop must end up with the
  # same versions as the machine the thresholds were calibrated on.
  "$PY" -m pip install -r requirements-lock.txt || died "Dependency install failed.

If a wheel failed to build, the usual cause is a Python other than 3.12 or a
non-arm64 machine. Scroll up for the failing package."
  echo "  Installed $("$PY" -m pip list 2>/dev/null | wc -l | tr -d ' ') packages"
fi

[ -x "$PY" ] || died "No .venv found. Run ./setup.sh without --verify first."

# -------------------------------------------------- 2. model + camera checks
say "Verifying the booth (downloads CLIP weights on first run)..."
if ! "$PY" scripts/preflight.py; then
  died "Preflight failed -- see above. The booth is NOT ready.

Do not treat this laptop as a working backup until preflight passes."
fi

# ------------------------------------------------------- 3. real server boot
# Preflight proves the parts work. This proves the whole thing starts, which is
# what actually happens on event day.
say "Starting the server once, end to end..."
"$PY" -m uvicorn server:app --host 127.0.0.1 --port "$PORT" \
  --timeout-graceful-shutdown 3 > .setup-server.log 2>&1 &
SETUP_PID=$!
trap 'kill -9 $SETUP_PID 2>/dev/null || true' EXIT

UP=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then UP=1; break; fi
  kill -0 "$SETUP_PID" 2>/dev/null || break   # it exited; stop waiting
  sleep 1
done

# Reap it quietly. Without the wait, bash prints "Terminated: 15" as a job
# notice AFTER the success line -- which reads like a crash on a script whose
# whole purpose is telling the operator the booth is healthy.
kill "$SETUP_PID" 2>/dev/null || true
{ wait "$SETUP_PID"; } 2>/dev/null || true
kill -9 "$SETUP_PID" 2>/dev/null || true
trap - EXIT

if [ "$UP" -ne 1 ]; then
  echo
  tail -20 .setup-server.log >&2
  died "The server did not come up. Log above (full copy: .setup-server.log)."
fi
echo "  Server started and answered /health"
rm -f .setup-server.log

# ------------------------------------------------------------------ 4. done
cat <<'DONE'

====================================================================
  This laptop is ready to run the booth.
====================================================================

Start it:      ./run.sh
Stop it:       ./stop.sh
Re-check it:   ./setup.sh --verify

STILL TO DO BY HAND -- this laptop is not a finished booth yet:

  1. Calibrate it. The thresholds in config/settings.yaml came from the
     other laptop, its webcam, and its lighting. Run a capture round with
     real objects on THIS machine:

         ./.venv/bin/python scripts/capture_round.py

     (needs the server running with FOOLBOT_DEBUG=1)

  2. Check the camera index. If preflight listed more than one camera,
     make sure config/settings.yaml points at the USB webcam aimed at the
     table, not the laptop's built-in one.

  3. Voice is optional. The pre-generated audio cache is not in the repo;
     without it the robot speaks through the macOS voice, which is fine.

See docs/second-laptop.md for the whole story.
DONE
