#!/usr/bin/env bash
# Exercise 8's model server.
#
# Runs NATIVELY, like Ollama, and for the same reason: Docker Desktop on Apple
# Silicon cannot pass through the Metal GPU. nginx proxies /sleeper/ to it —
# see lab/nginx/default.conf.
#
# HF_HUB_OFFLINE=1 is not optional. mlx_lm.server resolves any model name it
# doesn't find locally by asking huggingface.co, so one typo in a notebook
# becomes an outbound request from a lab whose first ground rule is that it
# makes none. Offline mode turns that into a local error in 0.08s.
#
# The server is started from lab/models so that model ids are the same repo
# names attendees already use on the hub: "northwind/support-7b".
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS="$HERE/models"
VENV="$HERE/sleeper/.venv/bin/mlx_lm.server"
PORT="${SLEEPER_PORT:-8081}"
LOG="$HERE/state/sleeper.log"
PIDF="$HERE/state/sleeper.pid"

running() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }

case "${1:-status}" in
  start)
    if running; then echo "  already running (pid $(cat "$PIDF"))"; exit 0; fi
    [ -x "$VENV" ] || { echo "  ERROR: $VENV not found — see sleeper/README.md"; exit 1; }
    [ -d "$MODELS/northwind/support-7b" ] || { echo "  ERROR: models not staged. Run: make seed"; exit 1; }
    mkdir -p "$HERE/state"
    cd "$MODELS"
    HF_HUB_OFFLINE=1 nohup "$VENV" --port "$PORT" --host 0.0.0.0 >"$LOG" 2>&1 &
    echo $! > "$PIDF"
    printf "  starting"
    for _ in $(seq 1 30); do
      if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/v1/models"; then
        echo; echo "  up on :$PORT  (pid $(cat "$PIDF"))  log: state/sleeper.log"
        echo "  first request loads ~2.7 GB of weights and takes ~5s."
        exit 0
      fi
      printf "."; sleep 1
    done
    echo; echo "  did not come up — check $LOG"; exit 1
    ;;
  stop)
    if running; then kill "$(cat "$PIDF")"; rm -f "$PIDF"; echo "  stopped";
    else echo "  not running"; fi
    ;;
  status)
    if running; then echo "  running (pid $(cat "$PIDF")) on :$PORT";
    else echo "  not running — start it with: make sleeper"; fi
    ;;
  *) echo "usage: sleeper.sh {start|stop|status}"; exit 2 ;;
esac
