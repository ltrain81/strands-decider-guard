# Shared helpers for deploy.sh / ctl.sh / destroy.sh / doctor.sh. Source it; do not run it.
# shellcheck shell=bash

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUTS="$ROOT/outputs.json"
STACK="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["context"]["stackName"])' "$ROOT/cdk/cdk.json")"

if [ -t 1 ]; then B=$'\033[1m' G=$'\033[32m' Y=$'\033[33m' R=$'\033[31m' N=$'\033[0m'; else B="" G="" Y="" R="" N=""; fi
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
fail() { printf '  %s✗%s %s\n' "$R" "$N" "$*"; }
die()  { printf '%serror:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
step() { printf '\n%s%s%s\n' "$B" "$*" "$N"; }

# out KEY -> value from outputs.json (written by cdk deploy); empty if missing.
out() {
  [ -f "$OUTPUTS" ] || return 0
  python3 -c 'import json,sys; print(next(iter(json.load(open(sys.argv[1])).values())).get(sys.argv[2], ""))' "$OUTPUTS" "$1"
}

require_outputs() { [ -f "$OUTPUTS" ] || die "outputs.json not found. Deploy first: ./deploy.sh"; }

# use_region [REGION]: pin AWS_REGION for every aws/cdk call (shells often carry a different AWS_REGION).
use_region() {
  local r="${1:-}"
  [ -n "$r" ] || r="$(out Region)"
  [ -n "$r" ] || r="$(aws configure get region 2>/dev/null || true)"
  [ -n "$r" ] || die "no AWS region: pass --region (e.g. --region us-east-1)"
  export AWS_REGION="$r" AWS_DEFAULT_REGION="$r"
}

# invoke_guard JSON -> prints the guard Lambda's response
invoke_guard() {
  local f; f="$(mktemp)"
  aws lambda invoke --function-name "$(out GuardFunctionName)" --cli-binary-format raw-in-base64-out --payload "$1" "$f" >/dev/null
  cat "$f"; rm -f "$f"
}

# Write config.json for the console and upload the static files, then invalidate the CDN cache.
# Developer install page (install.html) assets under dev/: the hook files, the one-liner and the sign-in settings.
# Everything here is public on purpose: the API URL and the public client id are not secrets; the tokens are.
publish_dev_installer() {
  local dir="$1/dev" api; api="$(out GuardApiUrl)"
  [ -n "$api" ] || return 0
  mkdir -p "$dir"
  tar -czf "$dir/client.tar.gz" -C "$ROOT" client/decider_guard.py client/install.sh client/configure_agents.py guard/guard_core.py
  python3 "$ROOT/scripts/render_dev_installer.py" "$dir" "$(out AdminUrl)" "$api" "$(out DevClientId)" \
    "$(out DevIssuer)" "$(out DevAuthorizeUrl)" "$(out DevTokenUrl)"
}

publish_console() {
  local bucket; bucket="$(out ConsoleBucketName)"
  [ -n "$bucket" ] || { warn "policy console not deployed (console=false)"; return 0; }
  local tmp; tmp="$(mktemp -d)"
  cp -R "$ROOT/admin/web/." "$tmp/"
  python3 - "$tmp/config.json" <<EOF
import json, sys
json.dump({"mode": "cognito", "apiBase": "$(out ConsoleApiUrl)", "cognitoDomain": "$(out ConsoleLoginDomain)",
           "clientId": "$(out ConsoleClientId)", "redirectUri": "$(out AdminUrl)"}, open(sys.argv[1], "w"))
EOF
  publish_dev_installer "$tmp"
  aws s3 sync "$tmp" "s3://$bucket/" --delete --cache-control "no-cache" --only-show-errors
  aws cloudfront create-invalidation --distribution-id "$(out ConsoleDistributionId)" --paths '/*' >/dev/null
  rm -rf "$tmp"
  ok "console published: $(out AdminUrl)"
}

# Delete every object and version in a bucket (CloudFormation only deletes empty buckets).
empty_bucket() {
  local b="$1" batch
  [ -n "$b" ] || return 0
  aws s3api head-bucket --bucket "$b" 2>/dev/null || return 0
  while :; do
    batch="$(aws s3api list-object-versions --bucket "$b" --max-items 1000 --output json | python3 -c '
import json, sys
d = json.load(sys.stdin)
objs = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in (d.get("Versions") or []) + (d.get("DeleteMarkers") or [])]
print(json.dumps({"Objects": objs, "Quiet": True}) if objs else "")')"
    [ -n "$batch" ] || break
    aws s3api delete-objects --bucket "$b" --delete "$batch" >/dev/null
  done
  ok "emptied s3://$b"
}
