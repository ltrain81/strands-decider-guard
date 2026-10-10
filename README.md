# strands-decider-guard

Claude Code / Kiro CLI / Codex CLI 앞단에 [strands-decider](https://github.com/strands-labs/strands-decider)를 붙여,
**고객 개인정보(PII)·비밀 값이 LLM으로 넘어가기 전에 차단**하는 데모입니다. 모델 판단은 AWS(GPU EC2)에서 돌고,
각 개발자 PC에는 hook 하나만 설치합니다.

```
 개발자 PC                                        AWS (고객 계정, 기본 ap-northeast-2)
┌────────────────────────────┐   lambda:Invoke   ┌──────────────────────────────────────────────┐
│ Claude Code / Kiro / Codex │ ───(IAM, SigV4)──▶│ Guard Lambda (VPC)                           │
│   hook: decider_guard.py   │                   │  1) regex: 주민번호·카드(Luhn)·AWS 키 → 즉시 차단  │
│   - 프롬프트                 │ ◀── allow/ask/block│  2) strands-decider 질문 3개 (choice + yes/no) │
│   - Read/Write/Edit/Bash   │                   │        │ private IP :8000                    │
│   - Bash 출력 (Claude)      │                   │        ▼                                     │
└────────────┬───────────────┘                   │ EC2 g6.xlarge (L4) strands-decider 2B         │
             │ 통과한 것만                         │  (인바운드는 Lambda SG 에서만)                   │
             ▼                                   └──────────────────────────────────────────────┘
   Amazon Bedrock (Claude / Codex 모델)
```

문서:
- [LiteLLM 을 쓰는 고객](docs/LITELLM.md): 프록시 guardrail 로 서버 측에서 강제하는 방법
- [데모 영상 촬영 가이드](docs/DEMO_VIDEO.md)

## 무엇을 막나

| 단계 | Claude Code | Kiro CLI | Codex CLI |
|---|---|---|---|
| 프롬프트 제출 | **차단** (원문 비노출) | 차단 불가 → 모델에 "값을 쓰지 말라" 경고 주입 | **차단** |
| 파일 읽기 | Read 전에 파일 내용 검사 → **거부** | read_file 전 검사 → **거부** | (전용 도구 없음) `cat/head/grep x` 대상 파일 검사 |
| 파일 쓰기/수정 | Write/Edit 내용 검사 | fs_write/str_replace 검사 | apply_patch 추가 줄 검사 |
| 셸 | 명령 + 읽는 파일 검사, **출력도 검사 후 가림** | 명령 + 읽는 파일 | 명령 + 읽는 파일 |
| MCP / Web | 입력 검사 | 입력 검사 | 입력 검사 |

판정은 세 단계입니다.
- **block**: 강한 패턴(주민/외국인등록번호, Luhn 통과 카드번호, AWS 키, 개인키) 또는 decider 가 "민감 유형 + 실제 값"이라고 판단.
- **ask**: 애매한 경우. Claude Code 도구 호출은 사용자 확인창, 프롬프트는 차단하되 `#pii-ok` 로 시작하면 통과.
- **allow**: 나머지. 스키마(`CREATE TABLE ... phone`), 마스킹(`010-XXXX-XXXX`), 통계, 코드 변수명은 통과.

모든 사유는 **마스킹된 값만** 보여 주고, Lambda 로그와 로컬 `~/.decider-guard/audit.log` 에는 원문 없이 판정·유형·지연시간만 남깁니다.

## 빠른 시작

필요: AWS 자격 증명(배포 계정), Node 18+, Python 3.9+, AWS CLI v2.

```bash
git clone <this repo> && cd strands-decider-guard
./deploy.sh --region ap-northeast-2 --install-client           # 배포 + 이 PC에 hook 설치 (확인 프롬프트 있음)
# Claude Code 를 Bedrock 으로 쓰도록 같이 설정:  --claude-bedrock --bedrock-region us-west-2
```

다른 개발자 PC 에는:

```bash
client/install.sh --outputs outputs.json [--profile dev] [--agents claude,codex]
```
- 개발자 IAM 사용자/역할에 출력값 `InvokePolicyArn` 정책을 붙여야 합니다(`lambda:InvokeFunction` 하나).
- Codex 는 처음 실행 시 `/hooks` 에서 새 hook 을 **Trust** 해야 동작합니다.
- 제거: `client/install.sh --uninstall`. 기존 hook(다른 도구의 것)은 그대로 두고, 바꾼 파일은 `*.bak-decider-guard` 로 백업합니다.

AWS 없이 로컬에서 먼저 보고 싶으면 (Mac 에서 strands-decider 서버를 `127.0.0.1:8000` 에 띄운 상태):

```bash
client/install.sh --local
```

## 데모 시나리오 (`demo/`)

녹화용 스크립트 재생은 `demo/run_demo.sh`, 오른쪽 판정 로그 창은 `demo/watch_audit.sh` 입니다. 촬영 방법은 [docs/DEMO_VIDEO.md](docs/DEMO_VIDEO.md) 를 보세요.

```bash
cd demo && claude
```
1. `주민등록번호 900101-1234567 고객 가입 이력 조회 SQL 짜줘` → 프롬프트 차단 (모델 호출 없음)
2. `customers.csv 읽고 고객 수 알려줘` → Read 거부: 주민번호·이메일·휴대폰 패턴 (마스킹된 근거 표시)
3. `support_ticket.txt 요약해줘` → Read 거부: 정규식에 걸리는 값이 없는데도 decider 가 "건강 정보 + 특정인" 으로 판단
4. `architecture.md 한 줄 요약` → 통과 ("customer contact fields" 를 언급하지만 실제 값은 없음)
5. `cat customers.csv | head -2` 를 실행하라고 해 보기 → Bash 도 대상 파일을 검사해 거부

`tail -f ~/.decider-guard/audit.log` 를 옆에 띄워 두면 판정과 지연시간이 실시간으로 보입니다.

## 운영

```bash
./ctl.sh health    # Lambda → decider 상태 (모델, 디바이스)
./ctl.sh stop      # GPU 인스턴스 정지 (비용 절감). fail_mode=closed 면 그동안 프롬프트가 막힘
./ctl.sh start
./ctl.sh logs      # SSM 으로 설치 로그 / 서비스 로그
./destroy.sh       # 스택 전체 삭제 (스택 이름 입력 확인)
```

설정은 `~/.decider-guard/config.json`:
- `fail_mode`: `closed`(기본, guard 에 닿지 않으면 차단) / `open`.
- `override_token`: `ask` 판정 프롬프트를 통과시키는 접두어.
- `max_file_bytes`: 파일 검사 상한.

임계값은 Lambda 환경 변수 `GUARD_CAT_CONF`, `GUARD_BLOCK_P`, `GUARD_ASK_P`, `GUARD_MAX_CHUNKS` 로 조정합니다.

## 비용 (ap-northeast-2, 대략)

| 항목 | 비용 |
|---|---|
| EC2 g6.xlarge (L4 24GB) | $0.99/시간 (상시 가동 시 월 약 $720). 데모 후 `./ctl.sh stop` 또는 `./destroy.sh` |
| EBS gp3 100GB | 월 약 $9 (정지 중에도 과금) |
| 퍼블릭 IPv4 | 월 약 $3.6 |
| Lambda / CloudWatch | 데모 규모에서는 거의 0 |

CPU 인스턴스는 `--instance-type c7i.2xlarge` 처럼 바꿀 수 있습니다. 다만 CPU 지연시간은 측정하지 않았고 GPU 보다 수 배 느릴 것으로 예상합니다.

## 정확도 (합성 데이터, 로컬 Mac MPS 측정)

`tests/test_policy.py [--holdout] [decider_url]` 로 재현할 수 있습니다.

| 세트 | PII/비밀 검출 | 정상 텍스트 통과 | 비고 |
|---|---|---|---|
| 튜닝 세트 `tests/samples.py` (28) | 14/14 | 14/14 | 임계값을 이 세트로 정했으므로 낙관적인 수치 |
| 홀드아웃 `tests/holdout.py` (20) | 10/10 | 9/10 | 오탐: `SELECT name, email FROM users ...` |

- 판정 하나에 decider 호출 1회(질문 3개)가 들고, MPS 에서 중간값 약 190ms 입니다. 강한 패턴은 모델 호출 없이 1ms 이하.
- 샘플이 수십 개뿐이라 실제 성능을 대표하지 않습니다. 고객 데이터 형태로 샘플을 늘려 다시 재 보세요.

## 한계 (데모로서 알고 있어야 할 것)

- **hook 은 클라이언트 측 통제**라서 사용자가 끌 수 있습니다. 조직 강제는 Claude Code 관리형 설정(`/Library/Application Support/ClaudeCode/managed-settings.json` + `allowManagedHooksOnly`)으로 배포하세요.
- Kiro CLI 는 프롬프트를 막을 수 없고, Codex 는 hook 실패·타임아웃 시 통과(fail-open)합니다.
- **LiteLLM 프록시를 쓰는 고객**은 `litellm/decider_guardrail.py` 로 서버 측에서 강제할 수 있습니다. 같은 Lambda 를 호출하고, tool result(읽은 파일 내용)까지 검사합니다. 자세한 내용은 [docs/LITELLM.md](docs/LITELLM.md).
- Claude Code 의 Grep 결과나 `@파일` 참조처럼 hook 이 보지 못하는 경로가 있습니다. 서버 측 백스톱으로 **Bedrock Guardrails** 를 함께 쓰는 것을 권장합니다. 가드레일 버전을 만든 뒤 Claude Code 설정에 넣습니다:
  `"env": {"ANTHROPIC_CUSTOM_HEADERS": "X-Amzn-Bedrock-GuardrailIdentifier: <id>\nX-Amzn-Bedrock-GuardrailVersion: 1"}`
- 긴 파일은 1,500자 청크 최대 16개를 고르게 샘플링해서 검사합니다. 정규식은 전체(최대 256KB)를 봅니다.
- decider 서버는 인증이 없어서 Lambda SG 에서만 접근하도록 막았습니다. 동시 요청 처리 특성은 upstream 에서도 검증되지 않았습니다.
- `deciderRef` 는 strands-decider main 의 특정 커밋에 고정되어 있고(`cdk/cdk.json`), GPU AMI 는 배포 시점 최신 DLAMI 를 씁니다.

## 구조

```
deploy.sh / ctl.sh / destroy.sh   배포·운영 스크립트
cdk/                               CDK (TypeScript): VPC, EC2 GPU host, Guard Lambda, invoke policy
guard/guard_core.py                정책 (regex + decider). Lambda 와 로컬 모드가 같은 코드를 씀
guard/lambda_handler.py            Lambda 진입점
client/decider_guard.py            Claude/Kiro/Codex 공용 hook
client/install.sh                  hook 설치·제거 (configure_agents.py 가 각 설정 파일을 병합)
litellm/                           LiteLLM 프록시용 guardrail 과 예시 config
demo/                              가짜 고객 데이터, 녹화용 run_demo.sh, 판정 로그 뷰어 watch_audit.sh
docs/                              LiteLLM 연동, 데모 영상 촬영 가이드
tests/                             합성 샘플과 정책 테스트
```
