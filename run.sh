#!/usr/bin/env bash
# One-double-click launcher for the Fool the Robot prototype.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
PY=./.venv/bin/python

echo "Starting Fool the Robot server on http://127.0.0.1:${PORT} ..."
"$PY" -m uvicorn server:app --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

# Wait for readiness
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# Open Chrome (kiosk if available, else default browser)
if [ -d "/Applications/Google Chrome.app" ]; then
  open -a "Google Chrome" --args --autoplay-policy=no-user-gesture-required "http://127.0.0.1:${PORT}/"
else
  open "http://127.0.0.1:${PORT}/"
fi

wait $SERVER_PID
