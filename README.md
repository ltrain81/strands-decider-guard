# strands-decider-guard

[![ci](https://github.com/ltrain81/strands-decider-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/ltrain81/strands-decider-guard/actions/workflows/ci.yml)

**Stop customer PII and secrets before they reach the model.** This puts a small, fast decision model,
[strands-decider](https://github.com/strands-labs/strands-decider), in front of **Claude Code**, **Kiro CLI**
and **Codex CLI**, and optionally in your **LiteLLM** proxy. Prompts, file reads, edits and shell commands are
checked in a few hundred milliseconds. Sensitive ones are blocked, or the user is asked to confirm. Admins manage
what counts as sensitive in a web console. Most rules are plain-language questions, so admins don't need to write regex.

[한국어 README](README.ko.md)

```text
> Write SQL to look up the customer with resident number 900101-1234567

UserPromptSubmit operation blocked by hook:
[PII guard] Sensitive data detected; blocked (prompt).
  - [prompt] Resident registration number pattern found (900********567)
  Mask it or leave that data out and try again.
```

## Contents

- [How it works](#how-it-works)
- [Choose your path](#choose-your-path)
- [Quick start: local, no AWS](#quick-start-local-no-aws)
- [Quick start: AWS for a team](#quick-start-aws-for-a-team)
- [What is checked in each agent](#what-is-checked-in-each-agent)
- [Managing the policy](#managing-the-policy)
- [Operations and cost](#operations-and-cost)
- [Accuracy and latency](#accuracy-and-latency)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Repository layout](#repository-layout)
- [Development](#development)

More detail: [Configuration reference](docs/CONFIGURATION.md) · [Policy console guide](docs/ADMIN.md) ·
[LiteLLM](docs/LITELLM.md) · [Recording a demo](docs/DEMO_VIDEO.md)

## How it works

```text
 Developer machine                                      AWS (your account)                     or: this machine
┌──────────────────────────────┐  lambda:Invoke (IAM)  ┌───────────────────────────────────┐  ┌─────────────────────┐
│ Claude Code / Kiro / Codex   │ ────────────────────▶ │ Guard Lambda (in a VPC)           │  │ strands-decider     │
│  hook: decider_guard.py      │ ◀── allow/ask/block ─ │  1. regex: IDs, cards (Luhn), keys │  │ 127.0.0.1:8000      │
│  - prompts                   │                       │  2. strands-decider: 4 yes/no and  │  │ (make local)        │
│  - Read / Write / Edit / Bash│                       │     choice questions + your rules  │  └─────────────────────┘
│  - Bash output (Claude)      │                       │        │ private IP                │
└──────────────┬───────────────┘                       │        ▼                           │
               │ only what passed                      │ EC2 GPU host running the 2B model  │
               ▼                                       │ Policy: versioned S3, edited in    │
        Amazon Bedrock (or any model)                  │ the console (CloudFront + Cognito) │
                                                       └───────────────────────────────────┘
```

Each check makes **one** model call. The model reads the text once and answers several questions about it:
which kind of sensitive data appears, whether it is about a specific person, whether it holds real values
(not field names or placeholders), plus each of your custom rules. Clear-cut patterns, such as a resident
registration number or a valid card number, are blocked by regex without calling the model.
Reasons always show **masked** values, and nothing logs the original text.

## Choose your path

| You want to… | Path | Needs | Time |
|---|---|---|---|
| See it work on your laptop | [Local](#quick-start-local-no-aws) | Python 3.10+ (uv recommended); a Mac with Apple silicon or an NVIDIA GPU is fastest | ~10 min (first model download ~4 GB) |
| Protect a team's agents | [AWS](#quick-start-aws-for-a-team) | AWS credentials, Node 18+, AWS CLI v2, GPU instance quota | ~25 min |
| Enforce it in a LiteLLM proxy (cannot be bypassed by the user) | [LiteLLM](docs/LITELLM.md) | either of the above | +10 min |
| Let non-developers manage the rules | [Policy console](docs/ADMIN.md) | deployed with either path (local: no login) | — |

Not sure? Run the read-only check. It inspects your OS and GPU, tools, AWS credentials and the agents you
have installed, then prints the recommended next command:

```bash
git clone https://github.com/ltrain81/strands-decider-guard && cd strands-decider-guard
make doctor
```

## Quick start: local, no AWS

```bash
make local           # installs + starts strands-decider on 127.0.0.1:8000, installs the hooks (local mode)
make demo            # five scripted scenes with Claude Code (DEMO_LANG=ko for Korean)
make local-console   # policy console at http://127.0.0.1:8770, no login
```

- `make local` changes your agent configs: `~/.claude/settings.json`, `~/.kiro/hooks/decider-guard.json` and
  `~/.codex/hooks.json`. Existing hooks are kept, and each changed file is backed up as `*.bak-decider-guard`.
  Pick agents with `AGENTS=claude,codex`. Undo with `make uninstall`.
- Restart running agent sessions afterwards. **Codex** only runs new hooks after you approve them once with `/hooks`.
- The device is picked automatically (`mps` on Apple silicon, `cuda` with an NVIDIA GPU, else `cpu`).
  CPU works but takes seconds per check.

Try it yourself in `demo/en` (all data is synthetic):

```bash
cd demo/en && claude
> Read customers.csv and tell me how many customers there are     # denied: SSN, emails, phones
> Summarize support_ticket.txt                                     # denied: a named person's health data, no regex hit
> Summarize architecture.md                                        # allowed: mentions "contact fields", holds no values
```

## Quick start: AWS for a team

```bash
make preflight REGION=us-east-1                                   # read-only: credentials, GPU quota, IAM headroom
make deploy    REGION=us-east-1 ADMIN_EMAIL=you@example.com       # ~6 min stack + ~10 min first model load
make install                                                      # hooks on this machine, using outputs.json
```

The deploy creates a GPU host (default `g6.xlarge`) running strands-decider, a guard Lambda in the same VPC,
a versioned S3 bucket for the policy, and the policy console (CloudFront, Cognito login, HTTP API).
It ends with a smoke test and prints the console URL. Cognito emails the admin a temporary password.

On each teammate's machine:

```bash
git clone … && cd strands-decider-guard
client/install.sh --outputs outputs.json [--profile their-profile] [--agents claude,kiro,codex]
```

- Share `outputs.json` with teammates. It holds no secrets, only names and ARNs.
- Teammates' IAM identities need the **`InvokePolicyArn`** managed policy from the outputs, which grants
  `lambda:InvokeFunction` on the guard and nothing else.
- To point Claude Code at Amazon Bedrock at the same time, add `--claude-bedrock --bedrock-region us-west-2`.

## What is checked in each agent

| | Claude Code | Kiro CLI | Codex CLI | LiteLLM proxy |
|---|---|---|---|---|
| Prompt | **block** (prompt not shown to the model) | cannot block. The model is told not to use the values | **block** | **block** (HTTP 400) |
| File read | Read: content checked first, **deny** | read_file: **deny** | via shell: `cat/head/grep FILE` reads checked | every tool result sent to the model |
| Write / edit | Write, Edit, MultiEdit, NotebookEdit | fs_write, str_replace | apply_patch (added lines) | — |
| Shell | command + files it reads; **output is redacted** | command + files it reads | command + files it reads | — |
| MCP / web | tool input | tool input | tool input | — |
| "ask" verdict | confirmation dialog | blocks | blocks | blocks (configurable) |

## Managing the policy

The console has four tabs:
- **Policy:** sensitivity (lenient / balanced / strict) and block / ask / allow for each information type
  (resident ID, government ID, card/bank, contact, health, credentials).
  Also **your own rules written as yes/no questions**, e.g. "Does the text include unreleased launch plans for project
  Phoenix (PHX)?", an allowlist (company email domains, fake test names) and the message shown when something is blocked.
- **Test:** check sample text against unsaved settings.
- **Activity:** counts and recent blocks. No text is ever stored.
- **History:** every saved version, with rollback.

Saved changes reach every hook and the LiteLLM guardrail within 30 seconds; nothing is redeployed.
Guide: [docs/ADMIN.md](docs/ADMIN.md). Local: `make local-console`. AWS: `make console`, plus `make add-admin ADMIN_EMAIL=…` to add logins.

The console UI and block messages are available in English and Korean. They follow the browser and system
language by default; set them with `--language en|ko` (hooks) or the toggle (console).

## Operations and cost

```bash
make status | make health      # instance state, guard -> model health
make stop   | make start       # pause the GPU host when nobody needs it (the main cost)
./ctl.sh logs                  # host setup and service logs via SSM
make destroy                   # delete everything (asks you to type the stack name)
```

| Item | Approximate cost |
|---|---|
| GPU host `g6.xlarge` (NVIDIA L4) | ~$0.80/h in us-east-1, ~$0.99/h in ap-northeast-2. Stop it when idle |
| EBS gp3 100 GB | ~$8–9/month, also billed while the host is stopped |
| Public IPv4 for the host (no NAT gateway is created) | ~$3.6/month |
| Lambda, API Gateway, CloudFront, Cognito, S3, CloudWatch | near zero at team scale |

With `make stop` the hooks can't reach the guard. In `fail_mode: closed`, the default, they block until
`make start`. See [Configuration](docs/CONFIGURATION.md) for `fail_mode: open`.

## Accuracy and latency

Measured on synthetic samples with the balanced preset:
`make eval` runs [`tests/eval_accuracy.py`](tests/eval_accuracy.py) on the 30 tuning and 20 holdout samples.

| Sensitivity | Tuning set (30) | Holdout set (20) |
|---|---|---|
| Lenient | 2 misses (short health sentences) | 1 miss (driver's license number) |
| **Balanced** | all correct | 1 over-trigger: `SELECT name, email FROM users …` is "ask" |
| Strict | 1 over-trigger: a masking example is "ask" | 1 over-trigger: the same SQL is "ask" |

- The thresholds were tuned on the tuning set. While adding the "specific person" question, the holdout SQL
  score was also visible, so treat the holdout as not fully independent.
- Custom rules written in Korean were right on 9 of 10 sentences.
- **Latency:** about 200–300 ms per check with the model on an Apple-silicon Mac. End to end through
  hook → Lambda → GPU, Claude Code saw 0.3–0.65 s per hook. Regex-only blocks take under 1 ms.
- These are a few dozen synthetic sentences, not a benchmark. Check your own data on the console's Test tab
  before relying on it.

## Limitations

- **Client hooks are not enforcement.** A user can remove them. For enforcement:
  - Ship them via Claude Code managed settings (`managed-settings.json` + `allowManagedHooksOnly`).
  - Put the [LiteLLM guardrail](docs/LITELLM.md) in front of the models.
  - Or use Bedrock Guardrails as a server-side backstop:
    `ANTHROPIC_CUSTOM_HEADERS="X-Amzn-Bedrock-GuardrailIdentifier: <id>\nX-Amzn-Bedrock-GuardrailVersion: 1"`.
- **Gaps in the hooks:**
  - Kiro CLI cannot block prompts.
  - Codex treats hook failures and timeouts as "allow".
  - Claude Code's Grep results and `@file` mentions are not seen by the hooks.
- Long inputs are sampled: up to 16 chunks of 1,500 characters. The regexes still scan the whole text (up to 256 KB per file).
- The decider server has no authentication. Only the guard Lambda's security group can reach it. Its behaviour
  under concurrent requests is not documented upstream.
- The model is English-first. Korean text and Korean rules worked in our tests; check other languages before relying on them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Every prompt is blocked with "check failed" | The guard is unreachable: `make health`. A stopped host needs `make start`. For local mode, run `scripts/local-decider.sh status`. To allow while it is down, set `fail_mode: open` in `~/.decider-guard/config.json` |
| `make deploy`: GPU quota is 0 | Service Quotas → EC2 → *Running On-Demand G and VT instances*: request at least 4 vCPUs. Or use `--instance-type` with a type you have quota for |
| `Cannot exceed quota for RolesPerAccount` | Your account is at the IAM role limit. The stack adds 2 roles (3 with the console), and CDK bootstrap adds 5 once. Free some roles, request an increase, or use `DEPLOY_ARGS=--no-console` |
| `CREATE_FAILED … Invalid rule description` or other CloudFormation errors | Re-run `make deploy`. A stack in `ROLLBACK_COMPLETE` is recreated automatically |
| Codex ignores the hooks | Approve them once: start `codex` and run `/hooks`, or choose "Trust all" at startup |
| Kiro shows the prompt to the model anyway | Expected: Kiro CLI cannot block prompts. Tool calls are still blocked |
| Too many false positives | On the console's Test tab, try "Lenient", add allowlist entries, or set noisy types to "ask" |
| The hooks are too slow | Use a GPU (AWS or a Mac with Apple silicon). The first call after idle also pays Lambda and model warm-up |
| I want to remove everything | `make uninstall` on each machine, then `make destroy` |

## Repository layout

```text
Makefile                    entry points (make help)
deploy.sh ctl.sh destroy.sh AWS deploy / operate / delete
scripts/                    doctor.sh, local-decider.sh, lib.sh (shared helpers)
guard/guard_core.py         the engine: regex + decider + policy. Shared by the Lambda, console and local mode
guard/lambda_handler.py     guard Lambda entry point (policy from S3, 30 s cache)
client/                     decider_guard.py (one hook for all three agents), install.sh, configure_agents.py
admin/                      policy console: web/index.html, api/handler.py, dev_server.py (local, no login)
litellm/                    LiteLLM proxy guardrail + example config
cdk/                        CDK app (TypeScript): VPC, GPU host, Lambdas, S3, CloudFront, Cognito, API
demo/                       synthetic data (en/, ko/), run_demo.sh, watch_audit.sh
tests/                      test_offline.py (CI), test_with_model.py, eval_accuracy.py, samples
docs/                       configuration, console, LiteLLM, demo recording (English + .ko.md)
```

## Development

```bash
make test         # 27 offline tests (fake model) + shell syntax. CI runs this plus tsc and cdk synth
make test-model   # policy features against a running decider (make local first)
make eval         # accuracy on the synthetic samples
```

The engine is `guard/guard_core.py`, stdlib only. The Lambda, the console API, the local hook mode and the LiteLLM
guardrail all import it, so a change there applies everywhere. User-facing strings live in `TEXT` / `MSG` /
`I18N` tables (English and Korean). Add a language by adding a column to each.

strands-decider is pinned to a commit (`deciderRef` in `cdk/cdk.json`). Both the AWS host and `make local` use it.
