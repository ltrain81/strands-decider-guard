# Developer sign-in (`--auth jwt`)

[한국어](SIGN_IN.ko.md)

By default the hook calls the guard Lambda with the developer's AWS credentials (`lambda:InvokeFunction`). That only
works for people who have AWS access. With **sign-in**, developers log in once in the browser and the hook calls the
guard with a token:
- no AWS credentials on developer machines,
- every decision in the log carries the signed-in user,
- access is managed in one place (a user pool, or your company's IdP).

The [LiteLLM guardrail](LITELLM.md) does not need any of this: it runs on a server and calls the guard with that server's IAM role.

## How it works

```
 decider-guard login                                   every hook call
 ───────────────────                                   ───────────────
 hook ── opens browser ──► sign-in page (Cognito / IdP)
                               │ user signs in
 hook ◄── localhost:8723 ◄─────┘ one-time code
 hook ── code + PKCE verifier ──► token endpoint
 hook ◄── ID token (1 h) + refresh token (30 days)      hook ── Bearer ID token ──► API Gateway POST /guard/check
          saved in ~/.decider-guard/token.json (0600)                                │ JWT authorizer checks the
                                                                                     │ signature, issuer, audience, expiry
                                                        guard Lambda ◄───────────────┘ claims (email) → logged as "user"
```

1. **Sign-in = OAuth 2.0 authorization code + PKCE**, the same flow `aws sso login` and `gh auth login` use.
   - The hook makes a random value (the PKCE *verifier*) and sends only its SHA-256 hash with the sign-in request.
   - After sign-in the browser is redirected to `http://localhost:8723/callback` with a one-time **code**. The hook is listening there.
   - The hook exchanges the code **plus the verifier** for tokens. Someone who intercepts the code cannot use it without the verifier.
   - A random `state` value guards against forged redirects.
   - The hook is a *public client*: there is no client secret to leak, which is why PKCE is used.
2. **Tokens**
   - The **ID token** is a signed JWT valid for 1 hour, holding the user's email.
   - The **refresh token** (30 days by default, `-c devSessionDays=N`) lets the hook get a new ID token silently.
   - Both are saved in `~/.decider-guard/token.json`, readable only by you. `decider-guard logout` deletes it.
3. **Each check**
   - The hook sends `Authorization: Bearer <ID token>` to `POST /guard/check`.
   - API Gateway's JWT authorizer verifies the token before the guard runs. It checks the signature against the IdP's published keys, the issuer, the audience (the hooks' client id) and the expiry. Invalid tokens get 401 and never reach the Lambda.
   - The guard logs the user from the verified token, not from the request body.
   - Through this route the guard always applies the saved policy. Draft-policy tests stay console-only.
4. **When there is no valid sign-in**
   - With `fail_mode: closed` (the default) the hook blocks and says `Sign in with: decider-guard login`.
   - With `fail_mode: open` it allows the call and warns.

**Separate from the console.** Developers live in their own user pool (`Developers`). The admin console only accepts tokens from
the admin pool, so a developer sign-in never opens the policy console.

## Admin: set it up

1. Deploy with the console enabled (the default): `make deploy REGION=…`. The stack then has the sign-in API and the developer pool.
   It adds no IAM role, because API Gateway calls the guard through a resource policy.
2. Give developers a sign-in:
   - `make add-dev DEV_EMAIL=<address>`. Cognito emails a temporary password, and the user sets a new one on first sign-in.
   - At scale, federate the `Developers` pool with your corporate IdP (Cognito → *Sign-in experience → Federated identity providers*, SAML or OIDC).
     People then sign in with their company account, and leavers lose access when the IdP disables them.
   - Or skip Cognito: `DEPLOY_ARGS="-c devIssuer=https://<your-idp> -c devAudience=<client id>"` trusts your IdP directly.
     Register a public client there with the redirect URI `http://localhost:8723/callback` and scopes `openid email`.
3. Give developers the install command. `outputs.json` holds no secrets, so you can share it, or the values for the manual form:
   ```bash
   client/install.sh --outputs outputs.json --auth jwt
   # or
   client/install.sh --api-url <GuardApiUrl> --client-id <DevClientId> \
     --authorize-url <DevAuthorizeUrl> --token-url <DevTokenUrl>       # external IdP: --issuer <DevIssuer>
   ```
4. Revoke access: disable the user (`aws cognito-idp admin-disable-user`, or in your IdP). Renewal then fails at once.
   A token already issued keeps working until it expires (at most 1 hour).

The console's Logs tab shows the user in each row's details and CSV export, and the search box matches users as well as targets.

## Developer: install and sign in

```bash
client/install.sh --outputs outputs.json --auth jwt     # opens the browser to sign in, then runs a smoke test
decider-guard status                                    # guard health through the API
decider-guard login                                     # when the session expires (default 30 days)
decider-guard login --no-browser                        # over SSH: open the printed URL elsewhere, paste the address you land on
decider-guard logout
```

`decider-guard` lives in `~/.decider-guard/bin/` (linked into `~/.local/bin` if that exists).

## Limits

- Port 8723 must be free on the developer's machine during sign-in.
- Each check costs one API Gateway request (about $1 per million) on top of the Lambda.
- The API's integration timeout is 30 s; checks normally take under 1 s.
