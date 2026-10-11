#!/usr/bin/env bash
# Delete everything ./deploy.sh created: the whole CloudFormation stack, including the saved policy
# history and the console files. Local hooks are separate: client/install.sh --uninstall
#
#   ./destroy.sh [--region R] [--profile P]
set -euo pipefail
source "$(dirname "$0")/scripts/lib.sh"

REGION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --region) REGION="$2"; shift ;;
    --profile) export AWS_PROFILE="$2"; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done
use_region "$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

echo "This deletes stack ${B}$STACK${N} in $AWS_REGION (account $ACCOUNT):"
echo "  GPU host, Lambdas, VPC, policy bucket (all saved policy versions), console, Cognito users, logs."
read -r -p "Type the stack name to confirm: " a
[ "$a" = "$STACK" ] || { echo "aborted"; exit 1; }

step "Emptying buckets"
# Read the buckets from the stack itself, so this also works after a failed deploy or without outputs.json.
for b in $(aws cloudformation list-stack-resources --stack-name "$STACK" \
             --query "StackResourceSummaries[?ResourceType=='AWS::S3::Bucket'].PhysicalResourceId" --output text 2>/dev/null); do
  empty_bucket "$b"
done

step "Deleting stack"
(cd "$ROOT/cdk" && npx cdk destroy --force)
rm -f "$OUTPUTS"
echo
echo "Done. Remove the hooks on each machine with: client/install.sh --uninstall"
