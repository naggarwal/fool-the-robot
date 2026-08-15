#!/usr/bin/env bash
# Stop the Fool the Robot server, free its port, and RELEASE THE CAMERA.
#
# Two identities, because the port alone is not enough. The port is what blocks
# the next run.sh -- but a server that has been asked to quit closes its
# listening socket FIRST and only then waits for open connections. The booth tab
# holds a websocket that never closes on its own, so the process can sit there
# for hours: port free, camera still on, green light still lit. Checking only
# the port reported that as "already stopped" -- which is how a booth ends up
# with the webcam running after a clean-looking shutdown.
#
# So: sweep the port, then sweep for any surviving server process belonging to
# THIS directory. Scoping to our own cwd is what makes that safe; a bare
# `pkill -f uvicorn` would take out an unrelated project.
set -uo pipefail
cd "$(dirname "$0")"
HERE="$(pwd -P)"

PORT="${PORT:-8000}"

pids_on_port() { lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null; }

# Server processes started from this directory, whatever they are doing with
# the port right now.
pids_here() {
  local pid cwd
  for pid in $(pgrep -f "uvicorn server:app" 2>/dev/null); do
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    [ "$cwd" = "$HERE" ] && echo "$pid"
  done
}

PIDS="$(pids_on_port)"
if [ -z "$PIDS" ]; then
  echo "Nothing listening on port ${PORT}."
  LEFTOVERS="$(pids_here)"
  if [ -z "$LEFTOVERS" ]; then
    echo "No server process either -- already stopped."
    exit 0
  fi
  # This is the wedged-shutdown case. Do not wait politely a second time:
  # something already asked it to quit and it did not.
  echo "But a server from this folder is STILL RUNNING (camera may still be on):"
  echo "  ${LEFTOVERS//$'\n'/ }"
  # shellcheck disable=SC2086
  kill -9 $LEFTOVERS 2>/dev/null || true
  sleep 1
  if [ -n "$(pids_here)" ]; then
    echo "FAILED: could not kill $(pids_here | tr '\n' ' ')" >&2
    exit 1
  fi
  echo "Stopped. Camera released."
  exit 0
fi

echo "Stopping PID(s) on port ${PORT}: ${PIDS//$'\n'/ }"
# shellcheck disable=SC2086
kill $PIDS 2>/dev/null || true

# Give it a graceful window, then stop asking nicely.
for _ in $(seq 1 12); do
  [ -z "$(pids_on_port)" ] && break
  sleep 0.5
done

LEFT="$(pids_on_port)"
if [ -n "$LEFT" ]; then
  echo "Still up after 6s -- forcing: ${LEFT//$'\n'/ }"
  # shellcheck disable=SC2086
  kill -9 $LEFT 2>/dev/null || true
  sleep 1
fi

if [ -n "$(pids_on_port)" ]; then
  echo "FAILED: port ${PORT} is still held by: $(pids_on_port | tr '\n' ' ')" >&2
  exit 1
fi

# A freed port is NOT proof the camera is free. If the process closed its
# listener and then wedged on the booth tab's websocket, it is still holding the
# webcam -- so finish the job rather than declaring victory on the port.
STRAGGLERS="$(pids_here)"
if [ -n "$STRAGGLERS" ]; then
  echo "Port is free but the process is still up (holding the camera): ${STRAGGLERS//$'\n'/ }"
  # shellcheck disable=SC2086
  kill -9 $STRAGGLERS 2>/dev/null || true
  sleep 1
  if [ -n "$(pids_here)" ]; then
    echo "FAILED: could not kill $(pids_here | tr '\n' ' ')" >&2
    exit 1
  fi
fi

echo "Stopped. Port ${PORT} is free and the camera is released."
