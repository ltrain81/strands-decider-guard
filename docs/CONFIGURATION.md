# Configuration reference

Most people never need this page: `make local` or `make deploy` + `make install` pick sensible defaults, and
the detection policy is edited in the [policy console](ADMIN.md). This page lists every knob.

- [Hook (each developer machine)](#hook-each-developer-machine)
- [Policy](#policy)
- [AWS deployment](#aws-deployment)
- [Local decider](#local-decider)
- [LiteLLM guardrail](#litellm-guardrail)
- [Enforcing the hooks org-wide](#enforcing-the-hooks-org-wide)
- [IAM permissions](#iam-permissions)
- [Files this project writes](#files-this-project-writes)

## Hook (each developer machine)

`client/install.sh` writes `~/.decider-guard/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `backend` | `lambda` | `lambda`: call the deployed guard. `local`: run the engine in-process against a local decider |
| `function_name`, `region`, `profile` | from `outputs.json` | Guard Lambda and the AWS profile used to call it (default credential chain if `profile` is empty) |
| `decider_url` | `http://127.0.0.1:8000` | Local mode only |
| `fail_mode` | `closed` | `closed`: block when the guard cannot be reached. `open`: allow, with a warning |
| `language` | from `LANG` | `en` or `ko` for block messages and reasons |
| `max_file_bytes` | `262144` | How much of a file is read for checking |
| `override_token` | `#pii-ok` | A prompt starting with it passes an **ask** verdict (never a block) |

`client/install.sh` flags:

| Flag | Meaning |
|---|---|
| `--outputs outputs.json` | Read the guard name and region from a deployment |
| `--function-name N --region R` | Same, by hand |
| `--local [--decider-url URL]` | Local backend; needs a running decider (`scripts/local-decider.sh start`) |
| `--agents claude,codex` | Which agents to configure (default `claude,codex`; add `kiro` to opt in — it can block tool calls but not prompts). `--uninstall` removes all three |
| `--profile P` | AWS profile for calling the guard |
| `--language en\|ko` | Message language |
| `--fail-open` | Set `fail_mode: open` |
| `--claude-bedrock [--bedrock-region R]` | Also set `CLAUDE_CODE_USE_BEDROCK=1` / `AWS_REGION` in Claude Code's settings (existing values are kept) |
| `--uninstall` | Remove the hooks (other hooks are untouched) |

Local mode reads `~/.decider-guard/policy.json` if it exists. The local console (`make local-console`) writes it.

## Policy

Stored as JSON: in S3 for AWS deployments (versioned; the console writes it), in `~/.decider-guard/policy.json`
locally. All keys are optional; missing keys take the defaults shown.

```json
{
  "sensitivity": "balanced",
  "categories": {
    "resident_id": "block", "gov_id": "block", "financial": "block",
    "contact": "block", "health": "block", "credential": "block"
  },
  "custom_rules": [
    {"id": "phx", "name": "Project Phoenix", "action": "block", "sensitivity": "balanced", "enabled": true,
     "question": "Does the text include unreleased schedules, revenue or launch plans for project 'Phoenix' (PHX)?"}
  ],
  "allow": {"email_domains": ["example.com"], "terms": ["Jane Doe"]},
  "message": "Mask customer data before use. Questions: #privacy-help",
  "patterns": "assist",
  "evidence": "off"
}
```

- `patterns`: `off` (the model decides alone), `strong` (only checksum/format-certain patterns: resident numbers, valid card
  numbers, AWS and private keys), `assist` (also email/phone/ID hints that the model then judges; default).
- `evidence`: `off` (default), `blocked` (keep the text of blocked/asked checks) or `all`. Text goes to the evidence bucket
  (encrypted, deleted after `evidenceDays`, default 30) and is shown in the console's Logs tab; each view is logged as admin activity.
  Local mode keeps it in `~/.decider-guard/evidence/` (files readable only by you).
- Actions are `block`, `ask` and `allow`. `allow` means the type is not checked at all.
- Limits: 20 rules, 300-character questions, 100 allowlist entries of up to 100 characters each.

Each category combines regex patterns and a model category:

| Category | Regex patterns | Model category |
|---|---|---|
| `resident_id` | `kr_resident_id` (strong) | — |
| `gov_id` | `kr_passport`, `us_ssn` | `government_id` |
| `financial` | `card_number` (strong, Luhn-checked), `bank_account` | `financial` |
| `contact` | `email`, `kr_mobile`, `phone_intl` | `contact` |
| `health` | — | `health` |
| `private_life` | — | `private_life` (a named person's HR/disciplinary, legal, criminal, immigration, beliefs, union, sexual orientation or family matters) |
| `credential` | `aws_access_key_id`, `aws_secret_key`, `private_key` (all strong) | `credential` |

- **Strong** patterns decide on their own, up to the category's action.
- Other patterns only count when the model agrees.

Sensitivity presets (from `PRESETS` in `guard/guard_core.py`, chosen by `bench/tune.py`; see [bench/TUNING.md](../bench/TUNING.md)):

| | lenient | balanced | strict | Used as |
|---|---|---|---|---|
| `cat` | 0.60 | 0.90 | 0.90 | probability mass on enabled sensitive categories needed for the main path |
| `named` | 0.35 | 0.35 | 0.35 | "names a specific person" threshold (main path and named-person path) |
| `named_cat` | off | 0.40 | 0.30 | named-person path: named + at least this sensitive mass → block |
| `weak_ps` | 0.30 | 0.30 | 0.15 | weak-pattern path: an email / phone / passport / … regex hit + at least this sensitive mass → block |
| `pattern` | 0.20 | 0.20 | 0.20 | main path: sensitive + weak regex hit + real-PII ≥ this → block |
| `block` | 0.85 | 0.60 | 0.60 | main path: sensitive + real-PII ≥ this → block |
| `ask` | 0.50 | 0.50 | 0.50 | main path: sensitive + real-PII ≥ this → ask |
| `cred_real` | 0.30 | 0 | 0 | a credential verdict also needs real-PII ≥ this (lets `${DB_PASSWORD}`-style placeholders pass) |
| `rule` | 0.70 | 0.50 | 0.35 | custom rule answer ≥ this → the rule's action (per-rule sensitivity) |

When the model server cannot be reached (host stopped by the schedule, Spot interruption, network), the guard **falls back to
regex-only checks**: strong patterns still block, weak patterns (email, phone, …) get *ask*, and the reason says so. After a
connection failure the model is skipped for 30 s, so a stopped host costs ~1.5 s once rather than a timeout on every call.

## AWS deployment

`./deploy.sh` flags: `--region`, `--profile`, `--instance-type`, `--admin-email`, `--no-console`, `--schedule`, `--utc-offset`,
`--spot` / `--on-demand`, `--preflight-only`,
`-y`, and `--install-client`. `--install-client` passes `--agents`, `--claude-bedrock`, `--bedrock-region`,
`--fail-open` and `--language` through to `install.sh`.

The CDK context lives in `cdk/cdk.json`. Override a value with `-c key=value` in `DEPLOY_ARGS`, or edit the file.

| Key | Default | Meaning |
|---|---|---|
| `instanceType` | `g6.xlarge` | GPU host. Alternatives: `g5.xlarge`, `g4dn.xlarge`. CPU types also work but are much slower |
| `modelId` | `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` | Hugging Face model served by the host |
| `deciderRef` | a pinned commit | strands-decider version (also used by `make local`) |
| `stackName` | `DeciderGuard` | CloudFormation stack name |
| `console` | `true` | `false` skips the policy console (one fewer IAM role, no CloudFront/Cognito/API) |
| `amiId` | — | Set automatically on redeploys so a newer GPU AMI does not replace the running host |
| `schedule`, `scheduleUtcOffset` | — , `9` | run the host only in this window, e.g. `MON-FRI 08:00-20:00` (`./deploy.sh --schedule … --utc-offset 9`); kept across redeploys, `--schedule none` removes it |
| `evidenceDays` | `30` | days before kept original text is deleted (evidence bucket lifecycle rule) |
| `spot` | `false` | run the host on Spot, a persistent request that stops on interruption (`--spot` / `--on-demand`; switching replaces the host) |

Guard Lambda environment:

| Variable | Default | Meaning |
|---|---|---|
| `DECIDER_URL` | the host's private IP | strands-decider endpoint |
| `POLICY_BUCKET`, `POLICY_KEY` | the stack's bucket, `policy.json` | where the console saves the policy |
| `GUARD_CHUNK_CHARS` | `1500` | characters per model call for long inputs |
| `GUARD_MAX_CHUNKS` | `16` | chunks per input. Longer inputs are sampled evenly, first and last chunk included |

Outputs in `outputs.json`:
- `GuardFunctionName`, `GuardFunctionArn`, `InvokePolicyArn`, `Region`
- `DeciderInstanceId`
- `AdminUrl`, `AdminUserPoolId`, `PolicyBucketName`, `AlertsTopicArn`, `AlarmPrefix`
- `Console*` (used by `ctl.sh publish-console`)

Monitoring and alerts (created by the stack, configured from the console's Alerts tab):

| Resource | What |
|---|---|
| Metric filters `DeciderGuard/Blocks`, `Asks`, `Checks` | counts from the guard log (used by the "block spike" alarm) |
| EventBridge rule (every 5 min) | calls the admin Lambda's health check, which publishes `DeciderGuard/GuardHealthy` |
| SNS topic | alert emails; recipients subscribe from the console |
| CloudWatch alarms `<stack>-guard_down`, `-guard_errors`, `-block_spike`, `-latency` | created and updated by the admin Lambda, not CloudFormation, so thresholds change without a redeploy. `destroy.sh` deletes them |

None of these needs an extra IAM role. The admin Lambda's role gets the SNS, CloudWatch alarm/metric, EC2 describe and Logs Insights permissions.

## Local decider

`scripts/local-decider.sh start|stop|status|logs`, configured by environment variables:

| Variable | Default |
|---|---|
| `DECIDER_HOME` | `~/.strands-decider` (venv, model cache, logs) |
| `DECIDER_PORT` | `8000` |
| `DECIDER_DEVICE` | auto: `mps` on Apple silicon, `cuda` with `nvidia-smi`, else `cpu` |
| `DECIDER_MODEL` | `modelId` from `cdk/cdk.json` |

The local console is `python3 admin/dev_server.py [--port 8770] [--decider-url URL] [--home ~/.decider-guard]`.
It binds to 127.0.0.1 only and has no login.

## LiteLLM guardrail

`litellm/config.example.yaml` → `guardrails[].litellm_params`:

| Key | Default | Meaning |
|---|---|---|
| `backend` | `lambda` | `lambda` (invoke the guard) or `http` (call strands-decider directly; needs `guard_core.py` next to the guardrail) |
| `function_name`, `region` | — | guard Lambda (backend `lambda`) |
| `decider_url` | — | backend `http` |
| `block_on_ask` | `true` | treat **ask** as block (a proxy cannot ask the user) |
| `fail_mode` | `closed` | `closed` returns 503 when the guard is unreachable |
| `language` | `en` | `en` or `ko` |

## Enforcing the hooks org-wide

Users can edit their own settings. To make the Claude Code hooks mandatory, deploy them as **managed settings**
with your device-management tool:
- macOS: `/Library/Application Support/ClaudeCode/managed-settings.json`
- Linux: `/etc/claude-code/managed-settings.json`

```json
{
  "allowManagedHooksOnly": true,
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "DECIDER_GUARD_HOME=/opt/decider-guard /opt/decider-guard/venv/bin/python /opt/decider-guard/decider_guard.py claude", "timeout": 30, "onFailure": "block"}]}],
    "PreToolUse": [{"matcher": "^(Read|Write|Edit|MultiEdit|NotebookEdit|Bash|WebFetch|WebSearch|Task|Agent)$|^mcp__", "hooks": [{"type": "command", "command": "DECIDER_GUARD_HOME=/opt/decider-guard /opt/decider-guard/venv/bin/python /opt/decider-guard/decider_guard.py claude", "timeout": 30, "onFailure": "block"}]}],
    "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "DECIDER_GUARD_HOME=/opt/decider-guard /opt/decider-guard/venv/bin/python /opt/decider-guard/decider_guard.py claude", "timeout": 30, "onFailure": "block"}]}]
  }
}
```

- Install `decider_guard.py`, `guard_core.py`, a venv with boto3 and a `config.json` under `/opt/decider-guard`.
  `sudo DECIDER_GUARD_HOME=/opt/decider-guard client/install.sh --outputs outputs.json --agents none` does that
  without touching any user's agent config.
- For model traffic users cannot route around, use the [LiteLLM guardrail](LITELLM.md) or Bedrock Guardrails.

## IAM permissions

| Who | Needs |
|---|---|
| Whoever runs `deploy.sh` | CloudFormation, plus permission to create the stack's resources (EC2, VPC, Lambda, IAM roles, S3, CloudFront, Cognito, API Gateway, Logs). The usual CDK bootstrap roles cover this |
| Each developer (hook, `backend: lambda`) | the `InvokePolicyArn` managed policy only: `lambda:InvokeFunction` on the guard |
| LiteLLM host (`backend: lambda`) | the same `InvokePolicyArn` policy |
| Console admins | a Cognito user (`make add-admin`); no AWS access needed |

## Files this project writes

| Path | What |
|---|---|
| `~/.decider-guard/` | hook script, engine copy, `config.json`, local `policy.json`, `audit.log` (decisions only, no text) |
| `~/.claude/settings.json` | three hook entries (backed up to `settings.json.bak-decider-guard`) |
| `~/.kiro/hooks/decider-guard.json` | global Kiro hooks |
| `~/.codex/hooks.json` | two hook entries (backed up) |
| `~/.strands-decider/` | local decider venv, model cache, server log (`make local`) |
| `outputs.json` | deployment outputs (names and ARNs, no secrets) |
