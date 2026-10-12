# 개발자 로그인 (`--auth jwt`)

[English](SIGN_IN.md)

기본 방식에서는 hook 이 개발자의 AWS 자격 증명으로 guard Lambda 를 호출합니다 (`lambda:InvokeFunction`). AWS 접근이 있는
사람만 쓸 수 있는 방식입니다. **로그인** 방식에서는 개발자가 브라우저로 한 번 로그인하고, hook 은 토큰으로 guard 를 호출합니다.
- 개발자 PC 에 AWS 자격 증명이 필요 없습니다.
- 판정 로그마다 로그인한 사용자가 남습니다.
- 접근 권한을 한곳(사용자 풀 또는 회사 IdP)에서 관리합니다.

[LiteLLM guardrail](LITELLM.ko.md)은 서버에서 그 서버의 IAM 역할로 guard 를 호출하므로 이 설정이 필요 없습니다.

## 동작 원리

```
 decider-guard login                                   hook 호출마다
 ───────────────────                                   ─────────────
 hook ── 브라우저 열기 ──► 로그인 페이지 (Cognito / IdP)
                               │ 사용자 로그인
 hook ◄── localhost:8723 ◄─────┘ 일회용 code
 hook ── code + PKCE verifier ──► 토큰 엔드포인트
 hook ◄── ID 토큰(1시간) + refresh 토큰(30일)          hook ── Bearer ID 토큰 ──► API Gateway POST /guard/check
          ~/.decider-guard/token.json (0600) 에 저장                                 │ JWT authorizer 가 서명·발급자·
                                                                                     │ audience·만료를 검증
                                                        guard Lambda ◄───────────────┘ 토큰의 email → 로그의 "user"
```

1. **로그인 = OAuth 2.0 authorization code + PKCE.** `aws sso login`, `gh auth login` 과 같은 방식입니다.
   - hook 이 임의의 값(PKCE *verifier*)을 만들고, 로그인 요청에는 그 SHA-256 해시만 보냅니다.
   - 로그인하면 브라우저가 일회용 **code** 를 들고 `http://localhost:8723/callback` 으로 돌아옵니다. hook 이 거기서 기다립니다.
   - hook 은 code 와 **verifier** 를 함께 보내 토큰으로 바꿉니다. 중간에 code 를 가로채도 verifier 가 없으면 쓸 수 없습니다.
   - 임의의 `state` 값으로 위조된 리다이렉트를 막습니다.
   - hook 은 *public client* 라서 유출될 client secret 이 없습니다. 그래서 PKCE 를 씁니다.
2. **토큰**
   - **ID 토큰**은 1시간 유효한 서명된 JWT 이고, 사용자 email 이 들어 있습니다.
   - **refresh 토큰**(기본 30일, `-c devSessionDays=N`)으로 hook 이 새 ID 토큰을 조용히 받아 옵니다.
   - 둘 다 `~/.decider-guard/token.json` 에 본인만 읽을 수 있게 저장됩니다. `decider-guard logout` 으로 지웁니다.
3. **검사할 때마다**
   - hook 이 `Authorization: Bearer <ID 토큰>` 으로 `POST /guard/check` 를 호출합니다.
   - guard 가 실행되기 전에 API Gateway 의 JWT authorizer 가 토큰을 검증합니다. IdP 공개 키로 서명을 확인하고, 발급자, audience(hook 용 client id), 만료도 확인합니다. 잘못된 토큰은 401 을 받고 Lambda 까지 가지 않습니다.
   - guard 는 요청 본문이 아니라 검증된 토큰에서 사용자를 꺼내 로그에 남깁니다.
   - 이 경로로는 항상 저장된 정책이 적용됩니다. 초안 정책 테스트는 콘솔에서만 할 수 있습니다.
4. **유효한 로그인이 없을 때**
   - `fail_mode: closed`(기본값)이면 차단하고 `로그인하세요: decider-guard login` 이라고 안내합니다.
   - `open` 이면 경고와 함께 통과시킵니다.

**콘솔과는 분리되어 있습니다.** 개발자는 별도 사용자 풀(`Developers`)에 있습니다. 관리 콘솔은 관리자 풀의 토큰만 받으므로,
개발자 로그인으로는 정책 콘솔에 들어갈 수 없습니다.

## 관리자: 설정

1. 콘솔을 켠 상태(기본값)로 배포합니다: `make deploy REGION=…`. 그러면 스택에 로그인 API 와 개발자 풀이 생깁니다.
   API Gateway 는 리소스 정책으로 guard 를 호출하므로 IAM 역할은 늘지 않습니다.
2. 개발자 로그인을 만듭니다.
   - `make add-dev DEV_EMAIL=<주소>`. Cognito 가 임시 비밀번호를 메일로 보내고, 첫 로그인 때 새 비밀번호를 정합니다.
   - 규모가 크면 `Developers` 풀을 회사 IdP 와 연동하세요 (Cognito → *Sign-in experience → Federated identity providers*, SAML 또는 OIDC).
     그러면 회사 계정으로 로그인하고, 퇴사자는 IdP 에서 비활성화되는 즉시 갱신이 막힙니다.
   - Cognito 없이 회사 IdP 를 직접 쓸 수도 있습니다: `DEPLOY_ARGS="-c devIssuer=https://<IdP> -c devAudience=<client id>"`.
     IdP 에 redirect URI `http://localhost:8723/callback`, scope `openid email` 로 public client 를 등록하세요.
3. 개발자에게 설치 명령을 줍니다. `outputs.json` 에는 비밀 값이 없어서 공유해도 됩니다. 아니면 값을 직접 넘깁니다:
   ```bash
   client/install.sh --outputs outputs.json --auth jwt
   # 또는
   client/install.sh --api-url <GuardApiUrl> --client-id <DevClientId> \
     --authorize-url <DevAuthorizeUrl> --token-url <DevTokenUrl>       # 외부 IdP: --issuer <DevIssuer>
   ```
4. 접근을 회수하려면 사용자를 비활성화합니다 (`aws cognito-idp admin-disable-user`, 또는 IdP 에서). 그러면 갱신이 바로 실패합니다.
   이미 발급된 토큰은 만료될 때까지(최대 1시간) 동작합니다.

콘솔의 로그 탭에서는 각 행의 상세와 CSV 에 사용자가 나오고, 검색창에서 대상뿐 아니라 사용자로도 찾을 수 있습니다.

## 개발자: 설치와 로그인

```bash
client/install.sh --outputs outputs.json --auth jwt     # 브라우저로 로그인한 뒤 스모크 테스트
decider-guard status                                    # API 를 통한 guard 상태
decider-guard login                                     # 세션 만료 시 (기본 30일)
decider-guard login --no-browser                        # SSH 환경: 출력된 URL 을 다른 곳에서 열고, 도착한 주소를 붙여 넣기
decider-guard logout
```

`decider-guard` 는 `~/.decider-guard/bin/` 에 있습니다 (`~/.local/bin` 이 있으면 거기에도 링크).

## 한계

- 로그인하는 동안 개발자 PC 의 8723 포트가 비어 있어야 합니다.
- 검사마다 Lambda 외에 API Gateway 요청 1건(100만 건당 약 $1)이 추가됩니다.
- API 의 통합 타임아웃은 30초입니다. 보통 검사는 1초 안에 끝납니다.
