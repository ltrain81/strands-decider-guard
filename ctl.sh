#!/usr/bin/env bash
# Operate a deployment (reads outputs.json written by ./deploy.sh).
#
#   ./ctl.sh status              instance state and guard health
#   ./ctl.sh health              guard Lambda -> decider health (model, device)
#   ./ctl.sh stop | start        pause / resume the GPU host (the main cost)
#   ./ctl.sh logs                setup + service logs from the host (via SSM)
#   ./ctl.sh console             print the policy console URL
#   ./ctl.sh add-admin EMAIL     create a console login (Cognito emails a temporary password)
#   ./ctl.sh publish-console     re-upload the console files (after editing admin/web)
set -euo pipefail
source "$(dirname "$0")/scripts/lib.sh"
require_outputs
use_region

ID="$(out DeciderInstanceId)"
case "${1:-status}" in
  status)
    aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].[InstanceId,InstanceType,State.Name]' --output text
    invoke_guard '{"health": true}' | python3 -c 'import json,sys; d=json.load(sys.stdin); print("guard:", "ok -", d["decider"]["model"], "on", d["decider"]["device"]) if d.get("ok") else print("guard: not ready -", d.get("error"))' ;;
  health)
    invoke_guard '{"health": true}' | python3 -m json.tool ;;
  start)
    aws ec2 start-instances --instance-ids "$ID" --query 'StartingInstances[0].CurrentState.Name' --output text
    echo "the model reloads in ~1-2 min; check with: ./ctl.sh health" ;;
  stop)
    aws ec2 stop-instances --instance-ids "$ID" --query 'StoppingInstances[0].CurrentState.Name' --output text
    echo "stopping. Until ./ctl.sh start the guard checks with regexes only (strong patterns block, emails/phones ask)." ;;
  logs)
    CID="$(aws ssm send-command --instance-ids "$ID" --document-name AWS-RunShellScript \
      --parameters 'commands=["tail -n 30 /var/log/decider-setup.log","journalctl -u strands-decider -n 40 --no-pager"]' \
      --query Command.CommandId --output text)"
    sleep 4
    aws ssm get-command-invocation --command-id "$CID" --instance-id "$ID" --query StandardOutputContent --output text ;;
  console)
    url="$(out AdminUrl)"; [ -n "$url" ] && echo "$url" || echo "policy console not deployed (deployed with -c console=false)" ;;
  add-admin)
    [ -n "${2:-}" ] || die "usage: ./ctl.sh add-admin EMAIL"
    POOL="$(out AdminUserPoolId)"; [ -n "$POOL" ] || die "policy console not deployed"
    if aws cognito-idp admin-get-user --user-pool-id "$POOL" --username "$2" >/dev/null 2>&1; then
      echo "admin $2 already exists"
    else
      aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$2" --desired-delivery-mediums EMAIL \
        --user-attributes Name=email,Value="$2" Name=email_verified,Value=true >/dev/null
      echo "admin $2 created. A temporary password was emailed (check spam); sign in at $(out AdminUrl)"
    fi ;;
  publish-console)
    publish_console ;;
  -h|--help|help)
    sed -n '2,12p' "$0" ;;
  *)
    sed -n '2,12p' "$0" >&2; exit 2 ;;
esac
