#!/usr/bin/env bash
# Deploy the guard to AWS: GPU EC2 running strands-decider, guard Lambda, policy store and the policy
# console. Runs preflight checks first, waits for the model, smoke-tests, and can install local hooks.
#
#   ./deploy.sh --region us-east-1 [--profile P] [--admin-email you@example.com] [-y]
#
#   --instance-type T     GPU host type (default from cdk/cdk.json: g6.xlarge)
#   --admin-email E       create a policy-console login (Cognito emails a temporary password)
#   --no-console          skip the policy console (S3 + CloudFront + Cognito + API; adds one IAM role)
#   --schedule S          run the GPU host only in this window, e.g. "MON-FRI 08:00-20:00" (local time, see --utc-offset);
#                         outside it the guard checks with regexes only. "none" removes it. Kept across redeploys.
#   --utc-offset N        time zone of --schedule (default 9 = KST)
#   --network nat|public  nat (default): GPU host in a private subnet behind a NAT Gateway (~$47/month);
#                         public: host in a public subnet with a public IP, no NAT (cheaper demo setup). Kept across redeploys.
#   --spot / --on-demand  run the GPU host on Spot (~50% cheaper, can be interrupted; regexes keep checking meanwhile)
#                         or on-demand. Switching replaces the host (the model is downloaded again). Kept across redeploys.
#   --install-client      also install the hooks on this machine; passes through
#                         --agents claude,codex[,kiro]  --claude-bedrock  --bedrock-region R  --fail-open  --language en|ko
#   --preflight-only      run the checks and exit
#   -y                    do not ask for confirmation
set -euo pipefail
source "$(dirname "$0")/scripts/lib.sh"

PROFILE="" REGION="" IT="" YES="" INSTALL="" ADMIN_EMAIL="" CONSOLE=true ONLY_CHECK="" SCHEDULE="" UTC_OFFSET=9 MARKET="" NETWORK="" CLIENT_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift ;;
    --region) REGION="$2"; shift ;;
    --instance-type) IT="$2"; shift ;;
    --admin-email) ADMIN_EMAIL="$2"; shift ;;
    --no-console) CONSOLE=false ;;
    --schedule) SCHEDULE="$2"; shift ;;
    --utc-offset) UTC_OFFSET="$2"; shift ;;
    --network) NETWORK="$2"; shift ;;
    --spot) MARKET=spot ;;
    --on-demand) MARKET=on-demand ;;
    --preflight-only) ONLY_CHECK=1 ;;
    -y|--yes) YES=1 ;;
    --install-client) INSTALL=1 ;;
    --agents|--bedrock-region|--language) CLIENT_ARGS+=("$1" "$2"); shift ;;
    --claude-bedrock|--fail-open) CLIENT_ARGS+=("$1") ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "unknown option: $1 (see ./deploy.sh --help)" ;;
  esac
  shift
done

# ---------- preflight ----------
step "Preflight"
for c in node npm aws python3; do command -v "$c" >/dev/null || die "missing required tool: $c (see README > Prerequisites)"; done
node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)' || die "Node.js 18+ is required (found $(node --version))"
ok "tools: node $(node --version), $(aws --version 2>&1 | cut -d' ' -f1), python $(python3 -c 'import platform;print(platform.python_version())')"
[ -n "$PROFILE" ] && export AWS_PROFILE="$PROFILE"
use_region "$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || die "no valid AWS credentials${PROFILE:+ for profile $PROFILE} (try: aws sso login / aws configure)"
CALLER="$(aws sts get-caller-identity --query Arn --output text)"
ok "AWS account $ACCOUNT, region $AWS_REGION ($CALLER)"
IT="${IT:-$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["context"]["instanceType"])' "$ROOT/cdk/cdk.json")}"

STACK_EXISTS=""
aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1 && STACK_EXISTS=1
PROBLEMS=0

if [ -n "$(aws ec2 describe-instance-type-offerings --location-type region --filters Name=instance-type,Values="$IT" --query 'InstanceTypeOfferings[0].InstanceType' --output text 2>/dev/null | grep -v None)" ]; then
  ok "$IT is offered in $AWS_REGION"
else
  fail "$IT is not offered in $AWS_REGION. Pick another region or --instance-type (g5.xlarge, g6.xlarge, g4dn.xlarge)"; PROBLEMS=$((PROBLEMS + 1))
fi

if [ -z "$STACK_EXISTS" ] && [[ "$IT" == g* ]]; then
  VCPU="$(aws ec2 describe-instance-types --instance-types "$IT" --query 'InstanceTypes[0].VCpuInfo.DefaultVCpus' --output text 2>/dev/null || echo 4)"
  QUOTA="$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-DB2E81BA --query 'Quota.Value' --output text 2>/dev/null || echo "?")"
  if [ "$QUOTA" = "?" ]; then
    warn "could not read the 'Running On-Demand G and VT instances' quota; make sure it is >= $VCPU vCPUs"
  elif python3 -c "import sys; sys.exit(0 if float('$QUOTA') >= $VCPU else 1)"; then
    ok "GPU quota: $QUOTA vCPUs available for G instances (need $VCPU)"
  else
    fail "GPU quota is $QUOTA vCPUs, $IT needs $VCPU. Request an increase: Service Quotas > EC2 > 'Running On-Demand G and VT instances'"; PROBLEMS=$((PROBLEMS + 1))
  fi
fi

# IAM roles this deploy adds: CDK bootstrap (5, once per account+region), the stack (2, +1 with the console).
NEED=0
aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1 || NEED=5
if [ -n "$STACK_EXISTS" ]; then
  HAVE="$(aws cloudformation list-stack-resources --stack-name "$STACK" --query "length(StackResourceSummaries[?ResourceType=='AWS::IAM::Role' && ResourceStatus!='DELETE_COMPLETE'])" --output text)"
else
  HAVE=0
fi
WANT=2; [ "$CONSOLE" = true ] && WANT=3
NEED=$(( NEED + (WANT > HAVE ? WANT - HAVE : 0) ))
read -r ROLES ROLE_QUOTA < <(aws iam get-account-summary --query 'SummaryMap.[Roles,RolesQuota]' --output text)
if [ $(( ROLE_QUOTA - ROLES )) -ge "$NEED" ]; then
  ok "IAM roles: $ROLES of $ROLE_QUOTA used, this deploy adds $NEED"
else
  fail "IAM roles: $ROLES of $ROLE_QUOTA used, this deploy needs $NEED more. Delete unused roles, request a quota increase (Service Quotas > IAM > 'Roles per account'), or deploy with --no-console"
  PROBLEMS=$((PROBLEMS + 1))
fi

[ "$PROBLEMS" -eq 0 ] || die "$PROBLEMS preflight check(s) failed; nothing was deployed"
[ -n "$ONLY_CHECK" ] && { echo; echo "Preflight passed."; exit 0; }

cat <<EOF

${B}About to deploy stack $STACK${N}
  account   $ACCOUNT
  region    $AWS_REGION
  GPU host  $IT  (billed per hour while running; pause with ./ctl.sh stop)
  creates   VPC (no NAT), EC2 + 100 GB gp3, guard Lambda, versioned policy bucket, CloudWatch logs$( [ "$CONSOLE" = true ] && printf '\n            policy console: S3 + CloudFront, Cognito login, HTTP API + admin Lambda' )
EOF
if [ -z "$YES" ]; then read -r -p "Continue? [y/N] " a; [ "$a" = y ] || [ "$a" = Y ] || exit 1; fi

# ---------- deploy ----------
step "Deploying (first deploy: ~6 min for the stack, then the model loads)"
cd "$ROOT/cdk"
[ -d node_modules ] || npm ci --no-audit --no-fund
aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1 || npx cdk bootstrap "aws://$ACCOUNT/$AWS_REGION"
CTX=(-c instanceType="$IT" -c console="$CONSOLE")
# Keep the previous host schedule unless --schedule was given ("none" clears it).
if [ -z "$SCHEDULE" ]; then
  PREV="$(out Schedule)"; [ -n "$PREV" ] && [ "$PREV" != "always on" ] && SCHEDULE="${PREV% (UTC*}" && UTC_OFFSET="$(echo "$PREV" | sed -E 's/.*\(UTC\+?(-?[0-9.]+)\)/\1/')"
fi
[ -n "$SCHEDULE" ] && [ "$SCHEDULE" != none ] && CTX+=(-c schedule="$SCHEDULE" -c scheduleUtcOffset="$UTC_OFFSET")
NETWORK="${NETWORK:-$(out Network)}"
NETWORK="${NETWORK:-nat}"
CTX+=(-c network="$NETWORK")
MARKET="${MARKET:-$(out Market)}"
[ "$MARKET" = spot ] && CTX+=(-c spot=true)
# Keep a running GPU host: reuse its AMI instead of the newest DLAMI, which would replace the instance.
IID="$(out DeciderInstanceId)"
if [ -n "$IID" ]; then
  AMI="$(aws ec2 describe-instances --instance-ids "$IID" --query 'Reservations[0].Instances[0].ImageId' --output text 2>/dev/null || true)"
  [ -n "$AMI" ] && [ "$AMI" != None ] && CTX+=(-c amiId="$AMI")
fi
npx cdk deploy --require-approval never --outputs-file "$OUTPUTS" "${CTX[@]}"
cd "$ROOT"

[ "$CONSOLE" = true ] && { step "Publishing the policy console"; publish_console; }

step "Waiting for strands-decider (first boot installs packages and downloads the model: ~5-15 min)"
for i in $(seq 1 60); do
  H="$(invoke_guard '{"health": true}' || true)"
  if echo "$H" | grep -q '"ok": true'; then
    ok "ready: $(echo "$H" | python3 -c 'import json,sys; d=json.load(sys.stdin)["decider"]; print(d["model"], "on", d["device"])')"
    break
  fi
  [ "$i" = 60 ] && die "not ready after 20 min; see ./ctl.sh logs"
  printf '.'; sleep 20
done

step "Smoke test"
invoke_guard '{"text": "warm up"}' >/dev/null
# Texts come from the synthetic demo data, so this script holds no PII-like literals (the guard hook scans scripts too).
while IFS= read -r t; do
  D="$(invoke_guard "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$t")" | python3 -c 'import json,sys; r=json.load(sys.stdin); print("%-5s %7.1f ms" % (r["decision"], r["results"][0]["latency_ms"]))')"
  echo "  $D  <- ${t:0:60}"
done < <(python3 - "$ROOT" <<'PY'
import sys, os
root = sys.argv[1]
print(open(os.path.join(root, "demo", "en", "customers.csv")).read().splitlines()[1])
print(open(os.path.join(root, "demo", "ko", "customers.csv")).read().splitlines()[1])
print(open(os.path.join(root, "demo", "en", "support_ticket.txt")).read().replace("\n", " ").strip())
print("Show me an S3 bucket policy for cross-account access")
PY
)

if [ "$CONSOLE" = true ]; then
  step "Policy console"
  [ -n "$ADMIN_EMAIL" ] && "$ROOT/ctl.sh" add-admin "$ADMIN_EMAIL"
  echo "  $(out AdminUrl)"
  [ -z "$ADMIN_EMAIL" ] && echo "  create a login: ./ctl.sh add-admin you@example.com"
fi

step "Next"
if [ -n "$INSTALL" ]; then
  P=(); [ -n "$PROFILE" ] && P=(--profile "$PROFILE")
  "$ROOT/client/install.sh" --outputs "$OUTPUTS" "${P[@]}" "${CLIENT_ARGS[@]}"
else
  echo "  Install the hooks on each developer machine (their IAM identity needs the InvokePolicyArn output policy):"
  echo "    client/install.sh --outputs outputs.json${PROFILE:+ --profile $PROFILE}"
fi
