#!/usr/bin/env bash
# Install the PII guard hook for Claude Code / Kiro CLI / Codex CLI on this machine.
#
#   client/install.sh --outputs outputs.json                  # after ./deploy.sh (AWS backend)
#   client/install.sh --function-name NAME --region REGION [--profile P]
#   client/install.sh --local [--decider-url http://127.0.0.1:8000]   # no AWS: local strands-decider server
#   client/install.sh --outputs outputs.json --auth jwt       # developers sign in in the browser; no AWS credentials
#   client/install.sh --api-url URL --client-id ID (--issuer URL | --authorize-url URL --token-url URL)   # same, by hand
#   options: --agents claude,codex        which agents (default: claude,codex; add kiro to opt in, it can only block
#                                         tool calls; 'none' = just ~/.decider-guard). --uninstall removes all three
#            --language en|ko             block-message language (default: from LANG)
#            --fail-open                  allow (instead of block) when the guard is unreachable
#            --claude-bedrock [--bedrock-region R]   also point Claude Code at Amazon Bedrock
#            --no-login                   (--auth jwt) skip the sign-in and smoke test; run decider-guard login later
#            --uninstall                  remove the hooks again
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEST="${DECIDER_GUARD_HOME:-$HOME/.decider-guard}"
BACKEND=lambda FN="" REGION="" PROFILE="" URL="http://127.0.0.1:8000" AGENTS="" 
FAIL=closed BEDROCK="" BEDROCK_REGION="" UNINSTALL="" OUTPUTS="" LANGUAGE=""
AUTH=iam API_URL="" CLIENT_ID="" ISSUER="" AUTHORIZE_URL="" TOKEN_URL="" NO_LOGIN=""

while [ $# -gt 0 ]; do
  case "$1" in
    --outputs) OUTPUTS="$2"; shift ;;
    --function-name) FN="$2"; shift ;;
    --region) REGION="$2"; shift ;;
    --profile) PROFILE="$2"; shift ;;
    --local) BACKEND=local ;;
    --auth) AUTH="$2"; shift ;;
    --api-url) API_URL="$2"; AUTH=jwt; shift ;;
    --client-id) CLIENT_ID="$2"; shift ;;
    --issuer) ISSUER="$2"; shift ;;
    --authorize-url) AUTHORIZE_URL="$2"; shift ;;
    --token-url) TOKEN_URL="$2"; shift ;;
    --no-login) NO_LOGIN=1 ;;
    --decider-url) URL="$2"; shift ;;
    --agents) AGENTS="$2"; shift ;;
    --fail-open) FAIL=open ;;
    --language) LANGUAGE="$2"; shift ;;
    --claude-bedrock) BEDROCK=1 ;;
    --bedrock-region) BEDROCK_REGION="$2"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -n "$UNINSTALL" ]; then
  python3 "$HERE/configure_agents.py" uninstall --agents "${AGENTS:-claude,kiro,codex}"
  echo "hooks removed. $DEST was kept (audit.log); delete it with: rm -rf $DEST"
  exit 0
fi

if [ -n "$OUTPUTS" ]; then
  read -r FN REGION < <(python3 -c 'import json,sys; o=next(iter(json.load(open(sys.argv[1])).values())); print(o["GuardFunctionName"], o["Region"])' "$OUTPUTS")
  if [ "$AUTH" = jwt ]; then
    read -r API_URL CLIENT_ID ISSUER AUTHORIZE_URL TOKEN_URL < <(python3 -c 'import json,sys
o = next(iter(json.load(open(sys.argv[1])).values()))
if not o.get("GuardApiUrl"): sys.exit("this deployment has no sign-in API (redeploy with the console enabled)")
print(*(o.get(k) or "-" for k in ("GuardApiUrl", "DevClientId", "DevIssuer", "DevAuthorizeUrl", "DevTokenUrl")))' "$OUTPUTS")
    for v in ISSUER AUTHORIZE_URL TOKEN_URL; do [ "${!v}" = - ] && printf -v "$v" ''; done
  fi
fi
case "$AUTH" in iam) ;; jwt) BACKEND=api ;; *) echo "--auth must be iam or jwt" >&2; exit 2 ;; esac
if [ "$BACKEND" = api ] && { [ -z "$API_URL" ] || [ -z "$CLIENT_ID" ] || { [ -z "$ISSUER" ] && [ -z "$TOKEN_URL" ]; }; }; then
  echo "--auth jwt needs --outputs, or --api-url, --client-id and --issuer (or --authorize-url + --token-url)" >&2; exit 2
fi
if [ "$BACKEND" = lambda ] && [ -z "$FN" ]; then echo "need --outputs outputs.json, --function-name NAME or --local (see --help)" >&2; exit 2; fi
if [ "$BACKEND" = local ] && ! curl -sf -m 3 "$URL/health" >/dev/null; then
  echo "no strands-decider at $URL. Start one first:  scripts/local-decider.sh start" >&2; exit 1
fi

mkdir -p "$DEST"
cp "$HERE/decider_guard.py" "$ROOT/guard/guard_core.py" "$DEST/"

# Private venv with boto3 so the hook does not depend on the system Python's packages.
# Sign-in mode (backend api) needs only the standard library.
PY="$DEST/venv/bin/python"
if [ "$BACKEND" = api ]; then
  PY="$(command -v python3)"
elif [ ! -x "$PY" ]; then
  if command -v uv >/dev/null; then
    uv venv -q --python 3.12 "$DEST/venv" && uv pip install -q --python "$PY" boto3 || PY=""
  else
    python3 -m venv "$DEST/venv" && "$DEST/venv/bin/pip" install -q boto3 || PY=""
  fi
fi
[ -n "$PY" ] && [ -x "$PY" ] || { echo "venv setup failed; falling back to python3 + aws CLI" >&2; PY="$(command -v python3)"; }

python3 - "$DEST/config.json" <<EOF
import json, sys
cfg = {"backend": "$BACKEND", "function_name": "$FN", "region": "$REGION" or None, "profile": "$PROFILE" or None,
       "decider_url": "$URL", "fail_mode": "$FAIL", "language": "$LANGUAGE" or None}
if cfg["backend"] == "api":
    cfg["api_url"] = "$API_URL"
    cfg["auth"] = {k: v for k, v in {"client_id": "$CLIENT_ID", "issuer": "$ISSUER", "authorize_url": "$AUTHORIZE_URL",
                                       "token_url": "$TOKEN_URL"}.items() if v}
json.dump(cfg, open(sys.argv[1], "w"), indent=2)
EOF
chmod 600 "$DEST/config.json"

ARGS=(install --agents "${AGENTS:-claude,codex}" --command "\"$PY\" \"$DEST/decider_guard.py\"")
[ "$FAIL" = closed ] && ARGS+=(--fail-closed)
[ -n "$BEDROCK" ] && ARGS+=(--claude-bedrock --bedrock-region "${BEDROCK_REGION:-${REGION:-us-east-1}}")
[ -n "$PROFILE" ] && ARGS+=(--profile "$PROFILE")
python3 "$HERE/configure_agents.py" "${ARGS[@]}"

# `decider-guard login | logout | status | check TEXT`, linked into ~/.local/bin when that exists.
mkdir -p "$DEST/bin"
printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "$PY" "$DEST/decider_guard.py" > "$DEST/bin/decider-guard"
chmod 755 "$DEST/bin/decider-guard"
[ -d "$HOME/.local/bin" ] && ln -sf "$DEST/bin/decider-guard" "$HOME/.local/bin/decider-guard"

if [ "$BACKEND" = api ]; then
  if [ -n "$NO_LOGIN" ]; then
    echo; echo "done (no smoke test). Sign in with: $DEST/bin/decider-guard login"; exit 0
  fi
  echo; echo "sign in:"
  "$DEST/bin/decider-guard" login
fi

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
