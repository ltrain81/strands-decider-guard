#!/usr/bin/env bash
# Look at this machine and recommend how to run the guard. Read-only: changes nothing.
#
#   scripts/doctor.sh [--region R] [--profile P]
set -uo pipefail
source "$(dirname "$0")/lib.sh"

REGION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --region) REGION="$2"; shift ;;
    --profile) export AWS_PROFILE="$2"; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
  esac
  shift
done

have() { command -v "$1" >/dev/null 2>&1; }
pyver() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }
ge() { python3 -c "import sys; a=[int(x) for x in '$1'.split('.')]; b=[int(x) for x in '$2'.split('.')]; sys.exit(0 if a>=b else 1)"; }

step "Machine"
OS="$(uname -s)"; ARCH="$(uname -m)"
DEVICE=cpu
if [ "$OS" = Darwin ] && [ "$ARCH" = arm64 ]; then DEVICE=mps; elif have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then DEVICE=cuda; fi
ok "$OS $ARCH, local inference device: $DEVICE$( [ "$DEVICE" = cpu ] && echo ' (works, but expect seconds per check; AWS GPU recommended)')"

step "Tools"
PYOK=""; if have python3; then V="$(pyver python3)"; ge "$V" 3.10 && { ok "python3 $V"; PYOK=1; } || warn "python3 $V (3.10+ needed to run strands-decider locally; the hooks need 3.9+)"; else fail "python3 not found"; fi
have uv && ok "uv $(uv --version | cut -d' ' -f2) (used for fast installs)" || warn "uv not found (optional; pip is used instead)"
NODEOK=""; if have node; then node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)' && { ok "node $(node --version)"; NODEOK=1; } || warn "node $(node --version) (18+ needed to deploy with CDK)"; else warn "node not found (needed only to deploy to AWS)"; fi
have curl && ok "curl" || fail "curl not found"
AWSOK=""
if have aws; then
  ok "$(aws --version 2>&1 | cut -d' ' -f1)"
  use_region "$REGION" 2>/dev/null || true
  if ID="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null)"; then
    ok "AWS credentials: $ID${AWS_REGION:+ (region $AWS_REGION)}"; AWSOK=1
    case "$ID" in *Admin*|*admin*) warn "these look like admin credentials; deploy with a least-privilege role if you can" ;; esac
  else
    warn "no working AWS credentials (aws sso login / aws configure) - local mode only"
  fi
else
  warn "aws CLI not found (needed for the AWS deployment and the Lambda backend)"
fi

step "Coding agents"
AGENTS=()
check_agent() {  # name binary config-file
  if have "$2"; then
    AGENTS+=("$1")
    if [ -f "$3" ] && grep -q decider_guard.py "$3" 2>/dev/null; then ok "$1: installed, guard hook present ($3)"; else ok "$1: installed, guard hook not installed"; fi
  else
    echo "  - $1: not found"
  fi
}
check_agent claude claude "$HOME/.claude/settings.json"
check_agent kiro kiro-cli "$HOME/.kiro/hooks/decider-guard.json"
check_agent codex codex "$HOME/.codex/hooks.json"
if have python3 && python3 -c 'import litellm' 2>/dev/null || have litellm; then ok "LiteLLM found: you can also enforce the guard in the proxy (docs/LITELLM.md)"; fi

step "Guard backends"
if curl -sf -m 2 http://127.0.0.1:8000/health >/dev/null; then
  ok "local strands-decider running: $(curl -s http://127.0.0.1:8000/health | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model"], "on", d["device"])')"
else
  echo "  - local strands-decider: not running"
fi
if [ -f "$OUTPUTS" ] && [ -n "$AWSOK" ]; then
  H="$(invoke_guard '{"health": true}' 2>/dev/null || true)"
  if echo "$H" | grep -q '"ok": true'; then ok "AWS deployment ($(out Region)): healthy"; else warn "AWS deployment ($(out Region)): not healthy (./ctl.sh status; stopped hosts: ./ctl.sh start)"; fi
  [ -n "$(out AdminUrl)" ] && ok "policy console: $(out AdminUrl)"
else
  echo "  - AWS deployment: none (outputs.json not found)"
fi
if [ -f "$HOME/.decider-guard/config.json" ]; then
  ok "hook config: $(python3 -c 'import json,os; c=json.load(open(os.path.expanduser("~/.decider-guard/config.json"))); print("backend=%s fail_mode=%s" % (c.get("backend"), c.get("fail_mode")))')"
fi

step "Recommended next step"
AG="$(IFS=,; echo "${AGENTS[*]:-}")"
if [ ${#AGENTS[@]} -eq 0 ]; then
  echo "  No Claude Code, Kiro CLI or Codex CLI found. Install one first, or use the LiteLLM guardrail (docs/LITELLM.md)."
elif [ -f "$OUTPUTS" ]; then
  echo "  Install the hooks against your deployment:"
  echo "    client/install.sh --outputs outputs.json --agents $AG"
elif [ -n "$AWSOK" ] && [ -n "$NODEOK" ]; then
  echo "  Try it locally first (5 min), then deploy for your team:"
  echo "    make local            # local decider + hooks + console, no AWS"
  echo "    ./deploy.sh --region ${AWS_REGION:-us-east-1} --preflight-only && ./deploy.sh --region ${AWS_REGION:-us-east-1} --admin-email you@example.com"
elif [ -n "$PYOK" ]; then
  echo "  Run everything on this machine (no AWS):"
  echo "    make local"
else
  echo "  Install Python 3.10+ (or uv) to run locally, or AWS CLI + Node 18 to deploy."
fi
