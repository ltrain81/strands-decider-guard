#!/usr/bin/env python3
"""Add or remove the decider guard hooks in Claude Code, Kiro CLI and Codex CLI user configs.

  configure_agents.py install   --agents claude,kiro,codex --command "<py> <decider_guard.py>" [--fail-closed]
                                [--claude-bedrock --bedrock-region R [--profile P]]
  configure_agents.py uninstall --agents claude,kiro,codex

Existing hooks are kept; entries are recognised by "decider_guard.py" in their command, so
re-running is idempotent. Every file is backed up (<file>.bak-decider-guard) before it is changed.
"""
import argparse
import json
import os
import shutil

MARK = "decider_guard.py"
H = os.path.expanduser("~")
CLAUDE = os.path.join(H, ".claude", "settings.json")
KIRO = os.path.join(H, ".kiro", "hooks", "decider-guard.json")
CODEX = os.path.join(H, ".codex", "hooks.json")
CLAUDE_TOOLS = "^(Read|Write|Edit|MultiEdit|NotebookEdit|Bash|WebFetch|WebSearch|Task|Agent)$|^mcp__"


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak-decider-guard")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def strip_ours(hooks):
    """Remove our handlers from a {"Event": [{"matcher", "hooks": [...]}]} map."""
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            g = dict(g)
            g["hooks"] = [h for h in g.get("hooks", []) if MARK not in h.get("command", "")]
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    return hooks


def claude(install, a):
    s = load(CLAUDE)
    hooks = strip_ours(s.get("hooks", {}))
    if install:
        def handler(timeout=30):
            h = {"type": "command", "command": f"{a.command} claude", "timeout": timeout}
            if a.fail_closed:
                h["onFailure"] = "block"
            return h
        hooks.setdefault("UserPromptSubmit", []).append({"hooks": [handler()]})
        hooks.setdefault("PreToolUse", []).append({"matcher": CLAUDE_TOOLS, "hooks": [handler()]})
        hooks.setdefault("PostToolUse", []).append({"matcher": "Bash", "hooks": [handler()]})
        if a.claude_bedrock:
            env = s.setdefault("env", {})
            for k, v in (("CLAUDE_CODE_USE_BEDROCK", "1"), ("AWS_REGION", a.bedrock_region), ("AWS_PROFILE", a.profile)):
                if v and k not in env:
                    env[k] = v
                elif v and env.get(k) != v:
                    print(f"  claude: keeping existing env {k}={env[k]} (wanted {v})")
    if hooks:
        s["hooks"] = hooks
    else:
        s.pop("hooks", None)
    save(CLAUDE, s)
    print(f"  claude: {'installed' if install else 'removed'} hooks in {CLAUDE}")


def kiro(install, a):
    if install:
        cmd = {"type": "command", "command": f"{a.command} kiro"}
        save(KIRO, {"version": "v1", "hooks": [
            {"name": "decider-guard-prompt", "trigger": "UserPromptSubmit", "action": cmd, "timeout": 30},
            {"name": "decider-guard-tools", "trigger": "PreToolUse", "matcher": "*", "action": cmd, "timeout": 30},
        ]})
        print(f"  kiro: wrote {KIRO} (global, all agents). Kiro CLI cannot block prompts; it warns the model and blocks tool calls.")
    elif os.path.exists(KIRO):
        os.remove(KIRO)
        print(f"  kiro: removed {KIRO}")


def codex(install, a):
    s = load(CODEX)
    hooks = strip_ours(s.get("hooks", {}))
    if install:
        h = {"type": "command", "command": f"{a.command} codex", "timeout": 30, "statusMessage": "PII guard"}
        hooks.setdefault("UserPromptSubmit", []).append({"hooks": [h]})
        hooks.setdefault("PreToolUse", []).append({"matcher": "*", "hooks": [h]})
    s["hooks"] = hooks
    save(CODEX, s)
    print(f"  codex: {'installed' if install else 'removed'} hooks in {CODEX}")
    if install:
        print("  codex: start codex and approve the new hooks once (/hooks, or 'Trust all' at startup). Untrusted hooks do not run.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["install", "uninstall"])
    p.add_argument("--agents", default="claude,codex")
    p.add_argument("--command", default="")
    p.add_argument("--fail-closed", action="store_true")
    p.add_argument("--claude-bedrock", action="store_true")
    p.add_argument("--bedrock-region")
    p.add_argument("--profile")
    a = p.parse_args()
    if a.action == "install" and not a.command:
        p.error("--command is required for install")
    for agent in (x.strip() for x in a.agents.split(",")):
        if agent and agent != "none":  # "none": only set up ~/.decider-guard (e.g. for managed settings)
            {"claude": claude, "kiro": kiro, "codex": codex}[agent](a.action == "install", a)


if __name__ == "__main__":
    main()
