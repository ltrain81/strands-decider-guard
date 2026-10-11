# Using LiteLLM

[한국어](LITELLM.ko.md)

If your developers reach models through a **LiteLLM proxy**, the guard can run inside the proxy as a guardrail.
That is **stronger than the client hooks**:
- Every request passes through the proxy, so users cannot switch it off.
- Tool results, i.e. the file contents an agent read, are checked before they reach the model.

```text
Claude Code ──/v1/messages──┐
Codex CLI ───/v1/responses──┼─▶ LiteLLM proxy ──pre_call──▶ decider guard (Lambda or decider) ──▶ blocked: HTTP 400
SDKs / apps ─/chat/completions┘        │ passed
                                       ▼
                                 Amazon Bedrock (or any provider)
```

| | Client hooks | LiteLLM guardrail |
|---|---|---|
| Enforcement | users can remove them (use managed settings to prevent that) | always on for traffic through the proxy |
| File contents / tool results | some, before the tool runs (Read, `cat`, …) | **every tool result sent to the model** |
| User experience | blocked before running, with a reason. Claude Code can ask | an API 400 error. The conversation must be rewound |
| Kiro | supported (tool calls) | not applicable: Kiro uses its own backend |

**Use both.** They call the same guard, so there is one policy and one console. The hooks give fast, friendly feedback;
the proxy is the gate users cannot bypass.

## Setup

1. Deploy the guard (`make deploy`). Attach the `InvokePolicyArn` output to the role LiteLLM runs as (ECS task
   role, EC2 instance role, …).
2. Put `litellm/decider_guardrail.py` next to your LiteLLM config, or on `PYTHONPATH`.
   For `backend: http`, also copy `guard/guard_core.py`.
3. Add the `guardrails` block from [`litellm/config.example.yaml`](../litellm/config.example.yaml) to your config.
   `default_on: true` applies it to every request.
4. Restart the proxy.

```bash
export DECIDER_GUARD_FUNCTION=<GuardFunctionName from outputs.json>
PYTHONPATH=$(pwd)/litellm litellm --config litellm/config.example.yaml --port 4000
```

## Pointing the clients at the proxy

Claude Code:

```bash
export ANTHROPIC_BASE_URL=https://litellm.example.com
export ANTHROPIC_AUTH_TOKEN=<LiteLLM virtual key>
export ANTHROPIC_MODEL=claude-sonnet-4-6
export ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-4-5
unset CLAUDE_CODE_USE_BEDROCK
```

Codex (`~/.codex/config.toml`):

```toml
model_provider = "litellm"
model = "gpt-oss-120b"

[model_providers.litellm]
name = "LiteLLM"
base_url = "https://litellm.example.com/v1"
env_key = "LITELLM_API_KEY"
wire_api = "responses"
```

## Behaviour

- Only the **newest turn** is checked: the user prompt and tool results after the last assistant message.
  Earlier turns were checked when they were new. Texts that already passed are remembered by hash.
- System and developer prompts, and the model's own function-call arguments, are skipped.
- A block is HTTP 400. The error carries masked reasons (`reasons`) and your console block message.
  If the guard is unreachable, `fail_mode: closed` returns 503.
- The blocked message may stay in the client's history. In Claude Code, press `Esc` twice (rewind) or run `/clear`
  to continue in the same session.

## What was verified

Verified with LiteLLM 1.104.2, mock models and `backend: http` against a local decider:

| Endpoint | Result |
|---|---|
| `/v1/messages` | clean request 200; PII in the prompt 400; contact data inside a `tool_result` 400; health data with no regex hit 400 |
| `/v1/chat/completions` | card number 400; clean request 200 |
| `/v1/responses` | PII in the prompt 400; resident number inside `function_call_output` 400; clean request 200 |

Not verified yet:
- A real Claude Code or Codex client end to end through the proxy. The Claude Code build on the test machine
  was managed and ignored `ANTHROPIC_BASE_URL`.
- `backend: lambda` (LiteLLM → guard Lambda); check it after deploying.
- Responses. Only `pre_call` is implemented, so model output is not checked. Add a `post_call` hook if you need that.
