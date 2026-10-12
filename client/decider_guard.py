#!/usr/bin/env python3
"""PII guard hook for coding agents (Claude Code, Kiro CLI, Codex CLI), backed by strands-decider.

  decider_guard.py claude|kiro|codex   hook mode: reads the hook event JSON on stdin
  decider_guard.py check "some text"   manual check, prints the verdict
  decider_guard.py status [--json]     guard and model health
  decider_guard.py login [--no-browser]   sign in (backend "api"); logout removes the saved token

Config: ~/.decider-guard/config.json (written by install.sh). The audit log
(~/.decider-guard/audit.log) records decisions and finding types, never the text.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

HOME = os.environ.get("DECIDER_GUARD_HOME", os.path.expanduser("~/.decider-guard"))
DEFAULTS = {
    "backend": "lambda",          # lambda (IAM) | api (sign-in, see login) | local
    "api_url": "",                # backend api: POST endpoint (GuardApiUrl output)
    "auth": {},                   # backend api: client_id + authorize_url/token_url, or issuer (OIDC discovery)
    "function_name": "",
    "region": None,
    "profile": None,
    "decider_url": "http://127.0.0.1:8000",
    "fail_mode": "closed",        # closed: block when the guard is unreachable; open: allow with a warning
    "max_file_bytes": 262144,
    "override_token": "#pii-ok",  # a prompt starting with this passes an "ask" (uncertain) verdict, never a "block"
    "language": None,             # en | ko; default: from LANG / LC_ALL (ko_* -> ko, else en)
}

MSG = {
    "en": {
        "blocked": "[PII guard] Sensitive data detected; blocked ({where}).",
        "ask": "[PII guard] Possible sensitive data; confirmation needed ({where}).",
        "unreachable": "[PII guard] Could not reach the guard, so this was blocked (fail_mode=closed) ({where}).",
        "unreachable_hint": "Check the guard (make health / scripts/local-decider.sh status), or set fail_mode to open in ~/.decider-guard/config.json.",
        "default_hint": "Mask it or leave that data out and try again.",
        "prompt": "prompt", "tool": "tool {tool}", "bash_output": "Bash output",
        "output_hidden": "(the command output was hidden by the PII guard)",
        "kiro_warning": "[PII guard] The previous user message appears to contain sensitive data. Do not repeat, store, "
                        "write to files or send those values anywhere; ask the user to mask them and resend. Reason: {why}",
        "override": "If this is a false positive, resend the prompt starting with {token}",
        "guard_failed": "guard call failed: {e}",
        "failed_open": "[PII guard] check failed, allowing (fail_mode=open): {e}",
        "failed_closed": "[PII guard] check failed, blocking (fail_mode=closed): {e}",
        "login_needed": "not signed in to the PII guard, or the session expired",
        "login_hint": "Sign in with: decider-guard login   (then retry)",
        "login_open": "Opening the sign-in page. If no browser opens, visit:\n  {url}",
        "login_paste": "Open this URL in a browser, sign in, then paste the address you land on (http://localhost:8723/...):\n  {url}\n> ",
        "login_done": "Signed in as {user}. The session lasts until {until} unless revoked.",
        "login_page": "Sign-in received. Return to the terminal to see whether it finished; you can close this tab.",
        "logout_done": "Signed out (token removed).",
        "st_guard": "PII guard: reachable ({how})", "st_signed_in": "signed in as {user}", "st_iam": "AWS credentials",
        "st_local": "local mode, {url}",
        "st_model_ok": "Model: ready ({model} on {device})",
        "st_model_down": "Model: not available right now (GPU host stopped, starting, or outside its schedule).\n"
                         "  Checks still run with patterns only: certain formats block, emails and phone numbers ask.",
    },
    "ko": {
        "blocked": "[PII guard] 민감 정보가 감지되어 차단했습니다 ({where}).",
        "ask": "[PII guard] 민감 정보로 의심되어 확인이 필요합니다 ({where}).",
        "unreachable": "[PII guard] guard 에 연결하지 못해 차단했습니다 (fail_mode=closed) ({where}).",
        "unreachable_hint": "guard 상태를 확인하거나 (make health / scripts/local-decider.sh status), ~/.decider-guard/config.json 의 fail_mode 를 open 으로 바꾸세요.",
        "default_hint": "마스킹하거나 해당 데이터를 제외하고 다시 시도하세요.",
        "prompt": "프롬프트", "tool": "도구 {tool}", "bash_output": "Bash 출력",
        "output_hidden": "(명령 출력은 PII guard 가 가렸습니다)",
        "kiro_warning": "[PII guard] 직전 사용자 메시지에 민감 정보가 포함된 것으로 판단되었습니다. 그 값을 반복, 저장, 파일 기록, "
                        "외부 전송하지 말고, 사용자에게 마스킹 후 다시 요청하도록 안내하세요. 판단 근거: {why}",
        "override": "오탐이라면 프롬프트 앞에 {token} 를 붙여 다시 보내세요.",
        "guard_failed": "guard 호출 실패: {e}",
        "failed_open": "[PII guard] 검사 실패, 통과시킴 (fail_mode=open): {e}",
        "failed_closed": "[PII guard] 검사 중 오류가 발생해 차단했습니다 (fail_mode=closed): {e}",
        "login_needed": "PII guard 에 로그인하지 않았거나 세션이 만료되었습니다",
        "login_hint": "로그인하세요: decider-guard login   (그다음 다시 시도)",
        "login_open": "로그인 페이지를 엽니다. 브라우저가 열리지 않으면 이 주소로 가세요:\n  {url}",
        "login_paste": "브라우저에서 이 주소를 열어 로그인한 뒤, 도착한 주소(http://localhost:8723/...)를 붙여 넣으세요:\n  {url}\n> ",
        "login_done": "{user} 로 로그인했습니다. 세션은 {until} 까지 유지됩니다.",
        "login_page": "로그인 정보를 받았습니다. 완료 여부는 터미널에서 확인하세요. 이 탭은 닫아도 됩니다.",
        "logout_done": "로그아웃했습니다 (토큰 삭제).",
        "st_guard": "PII guard: 연결됨 ({how})", "st_signed_in": "{user} 로 로그인", "st_iam": "AWS 자격 증명",
        "st_local": "로컬 모드, {url}",
        "st_model_ok": "모델: 사용 가능 ({model}, {device})",
        "st_model_down": "모델: 지금은 쓸 수 없습니다 (GPU 호스트가 꺼져 있거나, 켜지는 중이거나, 운영 시간 밖).\n"
                         "  검사는 계속 패턴으로만 합니다: 형식이 확실한 값은 차단, 이메일·전화번호는 확인.",
    },
}


def language(cfg):
    if cfg.get("language") in MSG:
        return cfg["language"]
    loc = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return "ko" if loc.lower().startswith("ko") else "en"


def m(cfg, key, **kw):
    return MSG[language(cfg)][key].format(**kw)
READ_VERBS = {"cat", "head", "tail", "less", "more", "bat", "jq", "sed", "awk", "grep", "rg", "cut", "sort", "uniq", "column", "csvlook", "xsv"}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(HOME, "config.json")) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    return cfg


# ---------- backend ----------

def call_guard(cfg, items, client):
    if cfg["backend"] == "local":
        sys.path.insert(0, HOME)
        import guard_core
        policy = None
        try:  # written by the local admin console (admin/dev_server.py)
            with open(os.path.join(HOME, "policy.json")) as f:
                policy = json.load(f)
        except FileNotFoundError:
            pass
        out = guard_core.check_many(items, cfg["decider_url"], policy, language(cfg))
        out["basis"] = next((r.get("basis") for r in out["results"] if r["decision"] == out["decision"] and r.get("basis")), None)
        out["evidence"] = save_local_evidence(items, out, guard_core.normalize_policy(policy), client)
        return out
    payload = {"items": items, "client": client, "lang": language(cfg)}
    if cfg["backend"] == "api":
        return call_api(cfg, payload)
    try:
        import boto3
        from botocore.config import Config
        sess = boto3.Session(profile_name=cfg["profile"] or None, region_name=cfg["region"] or None)
        lam = sess.client("lambda", config=Config(read_timeout=25, connect_timeout=5, retries={"max_attempts": 1}))
        resp = lam.invoke(FunctionName=cfg["function_name"], Payload=json.dumps(payload).encode())
        out = json.load(resp["Payload"])
        if resp.get("FunctionError"):
            raise RuntimeError(f"guard Lambda error: {out.get('errorMessage', out)}")
        return out
    except ImportError:
        return _invoke_with_cli(cfg, payload)


def save_local_evidence(items, out, policy, client):
    """Local mode counterpart of the guard Lambda's evidence capture (policy "evidence": blocked | all)."""
    mode = policy.get("evidence", "off")
    if mode == "off" or (mode == "blocked" and out["decision"] == "allow"):
        return None
    import uuid
    eid = uuid.uuid4().hex
    folder = os.path.join(HOME, "evidence")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    body = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "client": client, "decision": out["decision"],
            "items": [{"source": i["source"], "text": i["text"][:4000], "truncated": len(i["text"]) > 4000, "decision": r["decision"],
                       "basis": r.get("basis"), "reasons": r.get("reasons", [])} for i, r in zip(items, out["results"])]}
    path = os.path.join(folder, eid + ".json")
    with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
        json.dump(body, f, ensure_ascii=False)
    return "local/" + eid


def _invoke_with_cli(cfg, payload):
    # Payload goes through 0600 temp files so the text never appears in the process list.
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.json"), os.path.join(d, "out.json")
        with open(os.open(src, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            json.dump(payload, f)
        cmd = ["aws", "lambda", "invoke", "--function-name", cfg["function_name"], "--cli-binary-format", "raw-in-base64-out",
               "--payload", f"file://{src}", dst, "--output", "json"]
        if cfg["region"]:
            cmd += ["--region", cfg["region"]]
        if cfg["profile"]:
            cmd += ["--profile", cfg["profile"]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise RuntimeError(r.stderr.strip()[:300])
        with open(dst) as f:
            return json.load(f)


# ---------- sign-in (backend "api") ----------
# OAuth 2.0 authorization code + PKCE with a loopback redirect, like `aws sso login` or `gh auth login`: the browser
# signs in at the IdP, the IdP redirects to this machine with a one-time code, and the code (plus the PKCE secret that
# never left this process) is exchanged for tokens. The ID token (1 h) goes to the guard API; the refresh token
# (default 30 days) renews it silently. Both live in token.json (0600). No AWS credentials are involved.

TOKEN_FILE = os.path.join(HOME, "token.json")
CALLBACK_PORT = 8723   # must match DEV_CALLBACK in cdk/lib/guard-stack.ts
REDIRECT = f"http://localhost:{CALLBACK_PORT}/callback"


class NotSignedIn(Exception):
    pass


_SSL = None


def ssl_context():
    """Verified TLS that also works when this Python ships without CA certificates (e.g. Homebrew with a broken
    ca-certificates link): honours SSL_CERT_FILE / REQUESTS_CA_BUNDLE / AWS_CA_BUNDLE, else on macOS falls back to the
    system and keychain roots (which include company CAs used by TLS-inspecting proxies)."""
    global _SSL
    if _SSL is not None:
        return _SSL
    import ssl
    bundle = next((os.environ[k] for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE") if os.environ.get(k)), None)
    ctx = ssl.create_default_context(cafile=bundle)
    if not bundle and not ctx.cert_store_stats().get("x509_ca") and sys.platform == "darwin":
        pem = os.path.join(HOME, "macos-roots.pem")
        if not os.path.exists(pem) or time.time() - os.path.getmtime(pem) > 7 * 86400:
            r = subprocess.run(["security", "find-certificate", "-a", "-p", "/System/Library/Keychains/SystemRootCertificates.keychain",
                                "/Library/Keychains/System.keychain"], capture_output=True, text=True, timeout=20)
            if "BEGIN CERTIFICATE" in r.stdout:
                os.makedirs(HOME, exist_ok=True)
                with open(pem + ".tmp", "w") as f:
                    f.write(r.stdout)
                os.replace(pem + ".tmp", pem)
        if os.path.exists(pem):
            ctx.load_verify_locations(cafile=pem)
    _SSL = ctx
    return ctx


def _http_json(url, data=None, headers=None, timeout=10):
    import urllib.parse
    import urllib.request
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    with urllib.request.urlopen(urllib.request.Request(url, data, headers or {}), timeout=timeout, context=ssl_context()) as r:
        return json.load(r)


def _endpoints(cfg):
    a = dict(cfg.get("auth") or {})
    if not (a.get("authorize_url") and a.get("token_url")) and a.get("issuer"):
        d = _http_json(a["issuer"].rstrip("/") + "/.well-known/openid-configuration")
        a.setdefault("authorize_url", d["authorization_endpoint"])
        a.setdefault("token_url", d["token_endpoint"])
    if not (a.get("client_id") and a.get("authorize_url") and a.get("token_url")):
        raise RuntimeError("backend api needs auth.client_id and auth.issuer (or authorize_url + token_url) in config.json")
    return a


def _claims(jwt):
    import base64
    part = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _save_token(tok, old=None):
    body = {"id_token": tok["id_token"], "refresh_token": tok.get("refresh_token") or (old or {}).get("refresh_token"),
            "expires_at": time.time() + int(tok.get("expires_in", 3600))}
    tmp = f"{TOKEN_FILE}.{os.getpid()}"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(body, f)
    os.replace(tmp, TOKEN_FILE)   # atomic: hooks running in parallel never see half a file
    return body


def id_token(cfg):
    """A valid ID token, refreshed when it expires within a minute. NotSignedIn when there is none to be had."""
    import urllib.error
    try:
        with open(TOKEN_FILE) as f:
            tok = json.load(f)
    except (OSError, ValueError):
        raise NotSignedIn()
    if tok.get("expires_at", 0) - 60 > time.time():
        return tok["id_token"]
    if not tok.get("refresh_token"):
        raise NotSignedIn()
    a = _endpoints(cfg)
    try:
        new = _http_json(a["token_url"], {"grant_type": "refresh_token", "client_id": a["client_id"], "refresh_token": tok["refresh_token"]})
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):   # refresh token expired, revoked, or the user was disabled
            raise NotSignedIn()
        raise
    return _save_token(new, tok)["id_token"]


def call_api(cfg, payload):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(cfg["api_url"], json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + id_token(cfg)})
    try:
        with urllib.request.urlopen(req, timeout=25, context=ssl_context()) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise NotSignedIn()
        raise RuntimeError(f"guard API HTTP {e.code}: {e.read()[:200].decode(errors='replace')}")


def login(cfg, browser=True):
    import base64
    import hashlib
    import http.server
    import secrets
    import urllib.parse
    a = _endpoints(cfg)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = a["authorize_url"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": a["client_id"], "redirect_uri": REDIRECT, "scope": a.get("scope", "openid email"),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    got = {}
    if browser:
        page = m(cfg, "login_page").encode()

        class Callback(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                if u.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                got.update({k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, *args):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), Callback)
        srv.timeout = 1
        print(m(cfg, "login_open", url=url), file=sys.stderr)
        import webbrowser
        webbrowser.open(url)
        deadline = time.time() + 300
        while not got and time.time() < deadline:
            srv.handle_request()
        srv.server_close()
    else:   # SSH / no browser here: sign in elsewhere and paste the address the browser was sent to
        back = input(m(cfg, "login_paste", url=url)).strip()
        got = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(back).query).items()}
    if got.get("error"):
        raise RuntimeError(f"sign-in failed: {got.get('error')} {got.get('error_description', '')}")
    if not got.get("code"):
        raise RuntimeError("sign-in timed out")
    if got.get("state") != state:
        raise RuntimeError("sign-in failed: state mismatch (stale or forged redirect)")
    tok = _http_json(a["token_url"], {"grant_type": "authorization_code", "client_id": a["client_id"], "code": got["code"],
                                      "redirect_uri": REDIRECT, "code_verifier": verifier})
    _save_token(tok)
    c = _claims(tok["id_token"])
    days = int((cfg.get("auth") or {}).get("session_days", 30))
    print(m(cfg, "login_done", user=c.get("email") or c.get("sub"), until=time.strftime("%Y-%m-%d", time.localtime(time.time() + days * 86400))))


# ---------- what to inspect ----------

def read_file(path, cfg, cwd=None):
    if cwd and not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            data = f.read(cfg["max_file_bytes"])
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None  # binary
    return data.decode("utf-8", errors="replace")


def files_read_by_command(cmd, cwd, cfg):
    """Files a shell command is obviously reading (cat x.csv, head -n 5 y, grep foo z | ...)."""
    out = []
    for segment in cmd.replace("&&", "|").replace(";", "|").split("|"):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        if not words or os.path.basename(words[0]) not in READ_VERBS:
            continue
        for w in words[1:]:
            if w.startswith("-"):
                continue
            text = read_file(w, cfg, cwd)
            if text:
                out.append((f"file:{os.path.basename(w)}", text))
    return out


def tool_items(agent, tool, ti, cwd, cfg):
    """(source, text) pairs to check for one tool call."""
    ti = ti or {}
    items = []
    if agent == "claude":
        if tool == "Read" and ti.get("file_path"):
            items.append((f"file:{os.path.basename(ti['file_path'])}", read_file(ti["file_path"], cfg)))
        elif tool == "Write":
            items.append(("write", ti.get("content")))
        elif tool == "Edit":
            items.append(("edit", ti.get("new_string")))
        elif tool == "MultiEdit":
            items.append(("edit", "\n".join(e.get("new_string", "") for e in ti.get("edits", []))))
        elif tool == "NotebookEdit":
            items.append(("edit", ti.get("new_source")))
        elif tool == "Bash":
            items.append(("bash", ti.get("command")))
            items += files_read_by_command(ti.get("command", ""), cwd, cfg)
        elif tool in ("WebFetch", "WebSearch", "Task", "Agent") or tool.startswith("mcp__"):
            items.append((tool, json.dumps(ti, ensure_ascii=False)))
    elif agent == "kiro":
        if tool in ("read_file", "fs_read") and ti.get("path"):
            items.append((f"file:{os.path.basename(ti['path'])}", read_file(ti["path"], cfg, cwd)))
        elif tool in ("fs_write", "fs_append"):
            items.append(("write", ti.get("text") or ti.get("content")))
        elif tool == "str_replace":
            items.append(("edit", ti.get("newStr")))
        elif tool in ("execute_bash", "execute_pwsh"):
            items.append(("bash", ti.get("command")))
            items += files_read_by_command(ti.get("command", ""), ti.get("cwd") or cwd, cfg)
        elif tool.startswith("mcp_") or "web" in tool or tool in ("use_subagent", "grep_search"):
            items.append((tool, json.dumps(ti, ensure_ascii=False)))
    elif agent == "codex":
        if tool == "Bash":
            items.append(("bash", ti.get("command")))
            items += files_read_by_command(ti.get("command", ""), cwd, cfg)
        elif tool == "apply_patch":
            patch = ti.get("command") or ti.get("patch") or ""
            added = "\n".join(l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
            items.append(("edit", added))
        elif tool.startswith("mcp__") or tool in ("spawn_agent", "web_search"):
            items.append((tool, json.dumps(ti, ensure_ascii=False)))
    return [{"source": s, "text": t} for s, t in items if t]


# ---------- verdicts ----------

def summarize(verdict):
    reasons = []
    for r in verdict.get("results", []):
        if r["decision"] != "allow":
            reasons += [f"[{r['source']}] {x}" for x in r.get("reasons", [])]
    label = next((r.get("basis_label") for r in verdict.get("results", []) if r["decision"] != "allow" and r.get("basis_label")), "")
    if label:
        reasons.append(label)
    return reasons


def audit(entry):
    try:
        with open(os.path.join(HOME, "audit.log"), "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def block_message(cfg, decision, reasons, where, custom="", unreachable=False, signed_out=False):
    head = "unreachable" if unreachable else "blocked" if decision == "block" else "ask"
    lines = [m(cfg, head, where=where)] + [f"  - {r}" for r in reasons[:6]]
    hint = m(cfg, "login_hint") if signed_out else m(cfg, "unreachable_hint") if unreachable else custom.strip() or m(cfg, "default_hint")
    lines.append(f"  {hint}")
    return "\n".join(lines)


def emit(cfg, agent, event, decision, message, reasons):
    """Write the agent-specific hook response and return the exit code."""
    if decision == "allow":
        return 0
    if agent == "claude":
        if event == "UserPromptSubmit":
            print(json.dumps({"decision": "block", "reason": message,
                              "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "suppressOriginalPrompt": True}}, ensure_ascii=False))
        elif event == "PreToolUse":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny" if decision == "block" else "ask",
                                                     "permissionDecisionReason": message}}, ensure_ascii=False))
        elif event == "PostToolUse":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": {
                "stdout": message + "\n" + m(cfg, "output_hidden"), "stderr": "", "interrupted": False, "isImage": False}}}, ensure_ascii=False))
        return 0
    if agent == "kiro":
        if event == "UserPromptSubmit":
            # Kiro CLI cannot block a prompt: steer the model instead (without repeating the values).
            why = "; ".join(r.split(" (")[0] for r in reasons)  # labels only, never the (masked) values
            print(m(cfg, "kiro_warning", why=why))
            return 0
        print(message, file=sys.stderr)
        return 2
    if agent == "codex":
        if event == "UserPromptSubmit":
            print(json.dumps({"decision": "block", "reason": message}, ensure_ascii=False))
        else:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}, ensure_ascii=False))
        return 0
    return 0


def run_hook(agent):
    cfg = load_config()
    ev = json.load(sys.stdin)
    event = ev.get("hook_event_name", "")
    event = {"userPromptSubmit": "UserPromptSubmit", "preToolUse": "PreToolUse", "postToolUse": "PostToolUse"}.get(event, event)
    tool = ev.get("tool_name", "")
    cwd = ev.get("cwd")
    if event == "UserPromptSubmit":
        prompt = ev.get("prompt", "")
        items, where = [{"source": "prompt", "text": prompt}], m(cfg, "prompt")
    elif event == "PreToolUse":
        items, where = tool_items(agent, tool, ev.get("tool_input"), cwd, cfg), m(cfg, "tool", tool=tool)
    elif event == "PostToolUse" and agent == "claude" and tool == "Bash":
        resp = ev.get("tool_response") or {}
        items, where = [{"source": "bash-output", "text": f"{resp.get('stdout', '')}\n{resp.get('stderr', '')}".strip()}], m(cfg, "bash_output")
        items = [i for i in items if i["text"]]
    else:
        return 0
    if not items:
        return 0

    t0 = time.time()
    unreachable = signed_out = False
    try:
        verdict = call_guard(cfg, items, agent)
        decision, reasons = verdict["decision"], summarize(verdict)
    except Exception as e:
        decision = "block" if cfg["fail_mode"] == "closed" else "allow"
        unreachable, signed_out = True, isinstance(e, NotSignedIn)
        reasons = [m(cfg, "login_needed") if signed_out else m(cfg, "guard_failed", e=str(e)[:200])]
        if decision == "allow":
            print(m(cfg, "failed_open", e=str(e)[:200]), file=sys.stderr)
        verdict = {"results": []}
    if decision == "ask" and event == "UserPromptSubmit":
        decision = "allow" if items[0]["text"].lstrip().startswith(cfg["override_token"]) else "block"
        if decision == "block":
            reasons.append(m(cfg, "override", token=cfg["override_token"]))
    if decision == "ask" and agent != "claude":
        decision = "block"  # only Claude Code can show an ask dialog
    if decision == "ask" and event == "PostToolUse":
        decision = "allow"

    audit({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": agent, "event": event, "tool": tool, "decision": decision,
           "types": sorted({f["type"] for r in verdict.get("results", []) for f in r.get("findings", []) if f["source"] != "degraded"}),
           "sources": [i["source"] for i in items], "ms": round((time.time() - t0) * 1000),
           "basis": verdict.get("basis"), "evidence": verdict.get("evidence")})
    return emit(cfg, agent, event, decision, block_message(cfg, decision, reasons, where, verdict.get("message", ""), unreachable, signed_out), reasons)


def status(cfg, as_json=False):
    """Guard and model health in plain words. A stopped model host is normal (schedule, Spot): checks fall back to patterns."""
    if cfg["backend"] == "local":
        sys.path.insert(0, HOME)
        import guard_core
        try:
            out = {"ok": True, "decider": guard_core.health(cfg["decider_url"], timeout=3)}
        except Exception as e:
            out = {"ok": False, "error": str(e)[:200]}
        how = m(cfg, "st_local", url=cfg["decider_url"])
    elif cfg["backend"] == "api":
        try:
            out = call_api(cfg, {"health": True})
        except NotSignedIn:
            print(m(cfg, "login_needed") + "\n" + m(cfg, "login_hint"))
            return 1
        with open(TOKEN_FILE) as f:
            c = _claims(json.load(f)["id_token"])
        how = m(cfg, "st_signed_in", user=c.get("email") or c.get("sub"))
    else:
        try:
            import boto3
            sess = boto3.Session(profile_name=cfg["profile"] or None, region_name=cfg["region"] or None)
            resp = sess.client("lambda").invoke(FunctionName=cfg["function_name"], Payload=b'{"health": true}')
            out = json.load(resp["Payload"])
        except ImportError:
            out = _invoke_with_cli(cfg, {"health": True})
        how = m(cfg, "st_iam")
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    print(m(cfg, "st_guard", how=how))
    d = out.get("decider") or {}
    print(m(cfg, "st_model_ok", model=d.get("model", "?"), device=d.get("device", "?")) if out.get("ok") else m(cfg, "st_model_down"))
    return 0


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd in ("claude", "kiro", "codex"):
        try:
            sys.exit(run_hook(cmd))
        except Exception as e:  # malformed event, bad config...: follow fail_mode rather than crash
            cfg = load_config()
            if cfg["fail_mode"] != "closed":
                print(m(cfg, "failed_open", e=e), file=sys.stderr)
                sys.exit(0)
            # Exit 2 blocks the prompt / tool call in all three agents (except Kiro prompts, which cannot be blocked).
            print(m(cfg, "failed_closed", e=str(e)[:200]), file=sys.stderr)
            sys.exit(2)
    cfg = load_config()
    if cmd == "check":
        text = " ".join(sys.argv[2:]) or sys.stdin.read()
        print(json.dumps(call_guard(cfg, [{"source": "cli", "text": text}], "cli"), ensure_ascii=False, indent=2))
    elif cmd == "login":
        try:
            login(cfg, browser="--no-browser" not in sys.argv[2:])
        except Exception as e:
            sys.exit(f"login failed: {e}")
    elif cmd == "logout":
        try:
            os.remove(TOKEN_FILE)
        except FileNotFoundError:
            pass
        print(m(cfg, "logout_done"))
    elif cmd == "status":
        sys.exit(status(cfg, as_json="--json" in sys.argv[2:]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
