#!/usr/bin/env python3
"""PII guard hook for coding agents (Claude Code, Kiro CLI, Codex CLI), backed by strands-decider.

  decider_guard.py claude|kiro|codex   hook mode: reads the hook event JSON on stdin
  decider_guard.py check "some text"   manual check, prints the verdict
  decider_guard.py status              backend health

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
    "backend": "lambda",          # lambda | local
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
        return guard_core.check_many(items, cfg["decider_url"], policy, language(cfg))
    payload = {"items": items, "client": client, "lang": language(cfg)}
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
    return reasons


def audit(entry):
    try:
        with open(os.path.join(HOME, "audit.log"), "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def block_message(cfg, decision, reasons, where, custom="", unreachable=False):
    head = "unreachable" if unreachable else "blocked" if decision == "block" else "ask"
    lines = [m(cfg, head, where=where)] + [f"  - {r}" for r in reasons[:6]]
    hint = m(cfg, "unreachable_hint") if unreachable else custom.strip() or m(cfg, "default_hint")
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
    unreachable = False
    try:
        verdict = call_guard(cfg, items, agent)
        decision, reasons = verdict["decision"], summarize(verdict)
    except Exception as e:
        decision = "block" if cfg["fail_mode"] == "closed" else "allow"
        unreachable = True
        reasons = [m(cfg, "guard_failed", e=str(e)[:200])]
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
           "types": sorted({f["type"] for r in verdict.get("results", []) for f in r.get("findings", [])}),
           "sources": [i["source"] for i in items], "ms": round((time.time() - t0) * 1000)})
    return emit(cfg, agent, event, decision, block_message(cfg, decision, reasons, where, verdict.get("message", ""), unreachable), reasons)


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
    elif cmd == "status":
        if cfg["backend"] == "local":
            sys.path.insert(0, HOME)
            import guard_core
            print(json.dumps(guard_core.health(cfg["decider_url"]), indent=2))
        else:
            try:
                import boto3
                sess = boto3.Session(profile_name=cfg["profile"] or None, region_name=cfg["region"] or None)
                resp = sess.client("lambda").invoke(FunctionName=cfg["function_name"], Payload=b'{"health": true}')
                out = json.load(resp["Payload"])
            except ImportError:
                out = _invoke_with_cli(cfg, {"health": True})
            print(json.dumps(out, indent=2))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
