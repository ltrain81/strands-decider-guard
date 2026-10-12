# LiteLLM 을 쓰는 고객

[English](LITELLM.md)

LiteLLM 프록시를 쓰는 고객이면 **서버 측 guardrail 로 붙일 수 있고, 클라이언트 hook 보다 강하게 막을 수 있습니다.**
모든 요청이 프록시를 지나가므로 사용자가 끌 수 없습니다. 에이전트가 읽은 파일 내용(tool result)도 모델에 가기 전에 검사됩니다.

```
Claude Code ──/v1/messages──┐
Codex CLI ───/v1/responses──┼─▶ LiteLLM proxy ──pre_call──▶ decider guard (Lambda 또는 decider 직접) ──▶ 차단 시 HTTP 400
SDK / 앱 ──/chat/completions┘        │ 통과
                                     ▼
                              Amazon Bedrock (또는 다른 제공자)
```

| | 클라이언트 hook | LiteLLM guardrail |
|---|---|---|
| 강제성 | 사용자가 끌 수 있음 (관리형 설정으로 보완) | 프록시를 거치면 항상 적용 |
| 파일 내용 / 도구 결과 | 도구 실행 전에 일부만 (Read, cat 등) | **모델로 가는 모든 tool result** |
| 사용자 경험 | 실행 전에 이유와 함께 막음, ask 확인창 | API 400 오류로 표시. 대화 되돌리기 필요 |
| Kiro | 지원 (도구 차단) | 해당 없음. Kiro 는 자체 백엔드라 커스텀 endpoint 를 못 씀 |

권장: **둘 다** 쓰세요. 같은 guard Lambda 를 호출하므로 정책이 하나로 유지됩니다.
hook 은 빠른 사전 차단과 안내를 맡고, LiteLLM 은 우회 불가능한 최종 관문을 맡습니다.

## 설치

1. `make deploy` 로 guard 를 배포합니다. LiteLLM 이 도는 역할(ECS task role, EC2 role 등)에 출력값 `InvokePolicyArn` 을 붙입니다.
2. `litellm/decider_guardrail.py` 를 LiteLLM 의 config 파일과 같은 디렉터리(또는 `PYTHONPATH`)에 둡니다.
   `backend: http` 를 쓰려면 `guard/guard_core.py` 도 같이 둡니다.
3. `litellm/config.example.yaml` 의 `guardrails` 블록을 기존 config 에 추가합니다. `default_on: true` 이면 모든 요청에 적용됩니다.
4. 프록시를 재시작합니다.

```bash
export DECIDER_GUARD_FUNCTION=<GuardFunctionName>
PYTHONPATH=$(pwd)/litellm litellm --config litellm/config.example.yaml --port 4000
```

## 클라이언트 연결

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

## 동작

- 검사 대상은 **가장 최근 턴**뿐입니다. 마지막 assistant 메시지 이후의 사용자 프롬프트와 tool result 를 봅니다.
  이전 턴은 새로 들어왔을 때 이미 검사했고, 통과한 텍스트는 해시로 기억해 다시 검사하지 않습니다.
- 검사마다 LiteLLM 키의 사용자(`user_email`, `user_id`, `key_alias`, 팀 중 설정된 것)가 `user` 로 남습니다.
  guard 는 프록시가 알려 준 값을 믿는 것이므로 `user_source: caller` 로 표시됩니다 (로그인한 hook 은 `token`).
- system / developer 프롬프트는 검사하지 않습니다. 모델이 직접 만든 function call 인자도 건너뜁니다.
- 차단 응답은 HTTP 400 입니다. 오류 메시지에 마스킹된 근거(`reasons`)와 콘솔의 차단 안내 문구가 들어 있습니다.
- 오류 메시지 언어는 guardrail 설정의 `language: en|ko` 로 정합니다.
- guard 에 닿지 않으면 `fail_mode: closed` 에서 503 으로 거절합니다.
- 차단된 메시지는 클라이언트 대화 기록에 남아 있을 수 있습니다. 같은 세션에서 계속하려면 Claude Code 는 `Esc` 두 번(rewind)이나 `/clear` 로 그 메시지를 되돌리세요.

## 검증한 것과 안 한 것

- LiteLLM 1.104.2 프록시에 mock 모델을 두고 HTTP 로 직접 확인했습니다 (decider 는 로컬 `backend: http`).
  - `/v1/messages`: 깨끗한 요청 200 / 프롬프트 PII 400 / tool_result 안의 연락처 400 / 정규식에 안 걸리는 건강 정보 400
  - `/v1/chat/completions`: 카드번호 400 / 깨끗한 요청 200
  - `/v1/responses`: 프롬프트 PII 400 / `function_call_output` 안의 주민번호 400 / 깨끗한 요청 200
- **실제 Claude Code·Codex 클라이언트를 프록시에 붙인 end-to-end 는 확인하지 않았습니다.** 테스트한 Mac 의 Claude Code 는 사내 관리 빌드라 `ANTHROPIC_BASE_URL` 대신 Bedrock 으로 나갔습니다.
- `backend: lambda` 경로(LiteLLM → Lambda)는 AWS 배포 후 확인해야 합니다.
- 스트리밍 응답은 검사하지 않습니다 (pre_call 만). 응답 쪽 검사가 필요하면 `post_call` 모드를 추가로 구현해야 합니다.
