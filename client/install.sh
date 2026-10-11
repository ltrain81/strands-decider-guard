#!/usr/bin/env bash
# Install the PII guard hook for Claude Code / Kiro CLI / Codex CLI on this machine.
#
#   client/install.sh --outputs outputs.json                  # after ./deploy.sh (AWS backend)
#   client/install.sh --function-name NAME --region REGION [--profile P]
#   client/install.sh --local [--decider-url http://127.0.0.1:8000]   # no AWS: local strands-decider server
#   options: --agents claude,kiro,codex   only these agents (default: all three; 'none' = just ~/.decider-guard)
#            --language en|ko             block-message language (default: from LANG)
#            --fail-open                  allow (instead of block) when the guard is unreachable
#            --claude-bedrock [--bedrock-region R]   also point Claude Code at Amazon Bedrock
#            --uninstall                  remove the hooks again
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEST="${DECIDER_GUARD_HOME:-$HOME/.decider-guard}"
BACKEND=lambda FN="" REGION="" PROFILE="" URL="http://127.0.0.1:8000" AGENTS="claude,kiro,codex"
FAIL=closed BEDROCK="" BEDROCK_REGION="" UNINSTALL="" OUTPUTS="" LANGUAGE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --outputs) OUTPUTS="$2"; shift ;;
    --function-name) FN="$2"; shift ;;
    --region) REGION="$2"; shift ;;
    --profile) PROFILE="$2"; shift ;;
    --local) BACKEND=local ;;
    --decider-url) URL="$2"; shift ;;
    --agents) AGENTS="$2"; shift ;;
    --fail-open) FAIL=open ;;
    --language) LANGUAGE="$2"; shift ;;
    --claude-bedrock) BEDROCK=1 ;;
    --bedrock-region) BEDROCK_REGION="$2"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -n "$UNINSTALL" ]; then
  python3 "$HERE/configure_agents.py" uninstall --agents "$AGENTS"
  echo "hooks removed. $DEST was kept (audit.log); delete it with: rm -rf $DEST"
  exit 0
fi

if [ -n "$OUTPUTS" ]; then
  read -r FN REGION < <(python3 -c 'import json,sys; o=next(iter(json.load(open(sys.argv[1])).values())); print(o["GuardFunctionName"], o["Region"])' "$OUTPUTS")
fi
if [ "$BACKEND" = lambda ] && [ -z "$FN" ]; then echo "need --outputs outputs.json, --function-name NAME or --local (see --help)" >&2; exit 2; fi
if [ "$BACKEND" = local ] && ! curl -sf -m 3 "$URL/health" >/dev/null; then
  echo "no strands-decider at $URL. Start one first:  scripts/local-decider.sh start" >&2; exit 1
fi

mkdir -p "$DEST"
cp "$HERE/decider_guard.py" "$ROOT/guard/guard_core.py" "$DEST/"

# Private venv with boto3 so the hook does not depend on the system Python's packages.
PY="$DEST/venv/bin/python"
if [ ! -x "$PY" ]; then
  if command -v uv >/dev/null; then
    uv venv -q --python 3.12 "$DEST/venv" && uv pip install -q --python "$PY" boto3 || PY=""
  else
    python3 -m venv "$DEST/venv" && "$DEST/venv/bin/pip" install -q boto3 || PY=""
  fi
fi
[ -n "$PY" ] && [ -x "$PY" ] || { echo "venv setup failed; falling back to python3 + aws CLI" >&2; PY="$(command -v python3)"; }

python3 - "$DEST/config.json" <<EOF
import json, sys
json.dump({"backend": "$BACKEND", "function_name": "$FN", "region": "$REGION" or None, "profile": "$PROFILE" or None,
           "decider_url": "$URL", "fail_mode": "$FAIL", "language": "$LANGUAGE" or None}, open(sys.argv[1], "w"), indent=2)
EOF
chmod 600 "$DEST/config.json"

ARGS=(install --agents "$AGENTS" --command "\"$PY\" \"$DEST/decider_guard.py\"")
[ "$FAIL" = closed ] && ARGS+=(--fail-closed)
[ -n "$BEDROCK" ] && ARGS+=(--claude-bedrock --bedrock-region "${BEDROCK_REGION:-${REGION:-us-east-1}}")
[ -n "$PROFILE" ] && ARGS+=(--profile "$PROFILE")
python3 "$HERE/configure_agents.py" "${ARGS[@]}"

echo
echo "smoke test:"
if echo '{"hook_event_name":"UserPromptSubmit","prompt":"Look up the customer with resident number 900101-1234567"}' | "$PY" "$DEST/decider_guard.py" claude | grep -q '"block"'; then
  echo "  PII prompt -> blocked (ok)"
else
  echo "  PII prompt was NOT blocked; check: $PY $DEST/decider_guard.py status" >&2; exit 1
fi
OUT=$(echo '{"hook_event_name":"UserPromptSubmit","prompt":"Show me an S3 bucket policy example"}' | "$PY" "$DEST/decider_guard.py" claude)
[ -z "$OUT" ] && echo "  clean prompt -> allowed (ok)" || { echo "  clean prompt was blocked: $OUT" >&2; exit 1; }
echo
echo "done. backend=$BACKEND fail_mode=$FAIL. audit log: $DEST/audit.log"
echo "restart running Claude Code / Kiro / Codex sessions to pick up the hooks."
