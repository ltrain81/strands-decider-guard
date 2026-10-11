#!/usr/bin/env bash
# Run strands-decider on this machine (no AWS). Installs it on first use.
#
#   scripts/local-decider.sh start | stop | status | logs
#
# Device is picked automatically: Apple silicon -> mps, NVIDIA GPU -> cuda, otherwise cpu.
# Override with DECIDER_DEVICE=cpu|mps|cuda. Other settings:
#   DECIDER_HOME   install dir        (default ~/.strands-decider)
#   DECIDER_PORT   port on 127.0.0.1  (default 8000)
#   DECIDER_MODEL  Hugging Face model (default from cdk/cdk.json)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

HOME_DIR="${DECIDER_HOME:-$HOME/.strands-decider}"
PORT="${DECIDER_PORT:-8000}"
MODEL="${DECIDER_MODEL:-$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["context"]["modelId"])' "$ROOT/cdk/cdk.json")}"
REF="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["context"]["deciderRef"])' "$ROOT/cdk/cdk.json")"
VENV="$HOME_DIR/venv"
BIN="$VENV/bin/strands-decider"
PIDFILE="$HOME_DIR/server.pid"
LOG="$HOME_DIR/server.log"
URL="http://127.0.0.1:$PORT"

healthy() { curl -sf -m 2 "$URL/health" >/dev/null 2>&1; }

device() {
  if [ -n "${DECIDER_DEVICE:-}" ]; then echo "$DECIDER_DEVICE"
  elif [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ]; then echo mps
  elif command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then echo cuda
  else echo cpu; fi
}

install() {
  [ -x "$BIN" ] && return 0
  step "Installing strands-decider into $VENV (one time, ~2-3 GB with PyTorch)"
  mkdir -p "$HOME_DIR"
  if command -v uv >/dev/null; then
    uv venv -q --python 3.12 "$VENV"
    VIRTUAL_ENV="$VENV" uv pip install -q "strands-decider @ git+https://github.com/strands-labs/strands-decider@$REF"
  else
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10+ is required (or install uv: https://docs.astral.sh/uv/)"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q "strands-decider @ git+https://github.com/strands-labs/strands-decider@$REF"
  fi
  ok "installed"
}

case "${1:-status}" in
  start)
    if healthy; then ok "already running on $URL"; exit 0; fi
    install
    DEV="$(device)"
    step "Starting strands-decider on $URL (device: $DEV). The first start downloads the model (~4 GB)."
    nohup "$BIN" serve "$MODEL" --device "$DEV" --port "$PORT" >"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
    for _ in $(seq 1 300); do
      healthy && { ok "ready: $(curl -s "$URL/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model"], "on", d["device"])')"; exit 0; }
      kill -0 "$(cat "$PIDFILE")" 2>/dev/null || { tail -20 "$LOG" >&2; die "server exited; full log: $LOG"; }
      sleep 1
    done
    die "timed out waiting for the server; see $LOG" ;;
  stop)
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"; ok "stopped" ;;
  status)
    if healthy; then curl -s "$URL/health" | python3 -m json.tool; else echo "not running (start with: scripts/local-decider.sh start)"; exit 1; fi ;;
  logs)
    tail -50 "$LOG" ;;
  -h|--help|help)
    sed -n '2,10p' "$0" ;;
  *)
    sed -n '2,10p' "$0" >&2; exit 2 ;;
esac
