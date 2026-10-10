#!/usr/bin/env bash
# Live view of guard decisions for the second pane of a demo recording (no raw text is ever logged).
LOG="${DECIDER_GUARD_HOME:-$HOME/.decider-guard}/audit.log"
touch "$LOG"
printf '\033[1mPII guard decisions\033[0m  (%s)\n\n' "$LOG"
read -r -d '' PY <<'EOF'
import json, sys
COLOR = {"block": "\033[1;31m", "ask": "\033[1;33m", "allow": "\033[1;32m"}
for line in sys.stdin:
    try:
        e = json.loads(line)
    except ValueError:
        continue
    what = e.get("tool") or "prompt"
    d = e["decision"]
    print(f"{e['ts'][11:]}  {e['agent']:6} {what:12} {COLOR.get(d, '')}{d.upper():5}\033[0m  {e['ms']:>5} ms  {', '.join(e['types'])}")
EOF
tail -n 0 -F "$LOG" | python3 -u -c "$PY"
