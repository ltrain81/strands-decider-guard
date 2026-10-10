#!/usr/bin/env bash
# Operate the deployed decider host:  ./ctl.sh start|stop|status|health|logs   (reads outputs.json)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ -f "$ROOT/outputs.json" ] || { echo "outputs.json not found; run ./deploy.sh first" >&2; exit 1; }
read -r ID FN REGION < <(python3 -c 'import json; o=next(iter(json.load(open("'"$ROOT"'/outputs.json")).values())); print(o["DeciderInstanceId"], o["GuardFunctionName"], o["Region"])')
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

case "${1:-status}" in
  start) aws ec2 start-instances --instance-ids "$ID" --query 'StartingInstances[0].CurrentState.Name' --output text
         echo "model reload takes ~1-2 min; check ./ctl.sh health" ;;
  stop)  aws ec2 stop-instances --instance-ids "$ID" --query 'StoppingInstances[0].CurrentState.Name' --output text
         echo "stopped: hooks will fail (fail_mode=closed blocks prompts) until ./ctl.sh start" ;;
  status) aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].[InstanceId,InstanceType,State.Name]' --output text ;;
  health) out="$(mktemp)"; aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out --payload '{"health": true}' "$out" >/dev/null
          python3 -m json.tool "$out"; rm -f "$out" ;;
  logs)  CID="$(aws ssm send-command --instance-ids "$ID" --document-name AWS-RunShellScript \
           --parameters 'commands=["tail -n 30 /var/log/decider-setup.log","journalctl -u strands-decider -n 40 --no-pager"]' \
           --query Command.CommandId --output text)"
         sleep 4; aws ssm get-command-invocation --command-id "$CID" --instance-id "$ID" --query StandardOutputContent --output text ;;
  *) echo "usage: $0 start|stop|status|health|logs" >&2; exit 2 ;;
esac
