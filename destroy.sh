#!/usr/bin/env bash
# Delete everything ./deploy.sh created (the whole CloudFormation stack). Local hooks: client/install.sh --uninstall
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
REGION="$(python3 -c 'import json; print(next(iter(json.load(open("'"$ROOT"'/outputs.json")).values()))["Region"])' 2>/dev/null || aws configure get region)"
STACK="$(python3 -c 'import json;print(json.load(open("'"$ROOT"'/cdk/cdk.json"))["context"]["stackName"])')"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
echo "This deletes stack $STACK in $REGION (account $(aws sts get-caller-identity --query Account --output text)): EC2 host, Lambda, VPC, IAM policy, logs."
read -r -p "Type the stack name to confirm: " a
[ "$a" = "$STACK" ] || { echo "aborted"; exit 1; }
cd "$ROOT/cdk" && npx cdk destroy --force
rm -f "$ROOT/outputs.json"
echo "done. Remove the hooks on each machine with: client/install.sh --uninstall"
