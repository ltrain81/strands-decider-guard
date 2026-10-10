#!/usr/bin/env bash
# Deploy the strands-decider PII guard to AWS (GPU EC2 running strands-decider + guard Lambda),
# wait until the model is loaded, smoke-test it, and optionally install the agent hooks locally.
#
#   ./deploy.sh [--profile P] [--region R] [--instance-type g6.xlarge] [-y]
#               [--install-client [--agents claude,kiro,codex] [--claude-bedrock [--bedrock-region R]] [--fail-open]]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROFILE="" REGION="" IT="" YES="" INSTALL="" CLIENT_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift ;;
    --region) REGION="$2"; shift ;;
    --instance-type) IT="$2"; shift ;;
    -y|--yes) YES=1 ;;
    --install-client) INSTALL=1 ;;
    --agents|--bedrock-region) CLIENT_ARGS+=("$1" "$2"); shift ;;
    --claude-bedrock|--fail-open) CLIENT_ARGS+=("$1") ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

for c in node npm aws python3; do command -v "$c" >/dev/null || { echo "missing required tool: $c" >&2; exit 1; }; done
[ -n "$PROFILE" ] && export AWS_PROFILE="$PROFILE"
REGION="${REGION:-$(aws configure get region || true)}"
[ -n "$REGION" ] || { echo "no region: pass --region" >&2; exit 1; }
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
CALLER="$(aws sts get-caller-identity --query Arn --output text)"
IT="${IT:-$(python3 -c 'import json;print(json.load(open("'"$ROOT"'/cdk/cdk.json"))["context"]["instanceType"])')}"

cat <<EOF
Deploying the decider guard
  account   $ACCOUNT ($CALLER)
  region    $REGION
  instance  $IT  (billed per hour while running; pause it with ./ctl.sh stop)
  creates   VPC (no NAT), EC2 + 100GB gp3, Lambda, IAM role and policy, CloudWatch log group
EOF
if [ -z "$YES" ]; then read -r -p "Continue? [y/N] " a; [ "$a" = y ] || [ "$a" = Y ] || exit 1; fi

cd "$ROOT/cdk"
[ -d node_modules ] || npm ci --no-audit --no-fund
if ! aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1; then
  npx cdk bootstrap "aws://$ACCOUNT/$REGION"
fi
npx cdk deploy --require-approval never --outputs-file "$ROOT/outputs.json" -c instanceType="$IT"
FN="$(python3 -c 'import json;print(next(iter(json.load(open("'"$ROOT"'/outputs.json")).values()))["GuardFunctionName"])')"

invoke() {  # invoke the guard Lambda with a JSON payload, print the response
  local out; out="$(mktemp)"
  aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out --payload "$1" "$out" >/dev/null
  cat "$out"; rm -f "$out"
}

echo
echo "Waiting for strands-decider to come up (first boot installs packages and downloads the model: ~5-15 min)"
for i in $(seq 1 60); do
  H="$(invoke '{"health": true}' || true)"
  if echo "$H" | grep -q '"ok": true'; then
    echo "  ready: $(echo "$H" | python3 -c 'import json,sys; d=json.load(sys.stdin)["decider"]; print(d["model"], "on", d["device"])')"
    break
  fi
  [ "$i" = 60 ] && { echo "  not ready after 20 min; check ./ctl.sh logs" >&2; exit 1; }
  printf '.'; sleep 20
done

echo
echo "Smoke test"
invoke '{"items":[{"source":"pii","text":"고객 김민수 010-2345-6789, 주민등록번호 900101-1234567"},{"source":"clean","text":"S3 버킷 정책 예시 보여줘"}]}' >/dev/null
for t in "주민등록번호 900101-1234567 고객 조회" "홍길동 환자는 우울증 치료 중이라 야간 연락 금지" "S3 버킷 정책 예시 보여줘"; do
  D="$(invoke "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1]}))' "$t")" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["decision"], r["results"][0]["latency_ms"], "ms")')"
  echo "  $D  <- $t"
done

echo
if [ -n "$INSTALL" ]; then
  P=(); [ -n "$PROFILE" ] && P=(--profile "$PROFILE")
  "$ROOT/client/install.sh" --outputs "$ROOT/outputs.json" "${P[@]}" "${CLIENT_ARGS[@]}"
else
  echo "Install the hooks on each developer machine (needs lambda:InvokeFunction; attach the InvokePolicyArn output):"
  echo "  client/install.sh --outputs outputs.json${PROFILE:+ --profile $PROFILE}"
fi
