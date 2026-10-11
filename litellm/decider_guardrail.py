"""LiteLLM proxy guardrail: block PII / secrets with the strands-decider guard before the model call.

Server-side counterpart of the client hooks. Every client that talks to the LiteLLM proxy
(Claude Code via /v1/messages, Codex via /v1/responses, SDKs via /v1/chat/completions) is
covered, and tool results (file contents the agent read) are checked too, which client hooks
cannot fully do.

Only the newest turn is checked: the messages after the last assistant message (the new user
prompt and tool results). Earlier turns were checked when they were new. Texts that already
passed are remembered by hash so retries are not re-scanned.

config.yaml:
  guardrails:
    - guardrail_name: decider-pii
      litellm_params:
        guardrail: decider_guardrail.DeciderGuardrail
        mode: pre_call
        default_on: true
        backend: lambda            # lambda (invoke the deployed guard Lambda) | http (call strands-decider directly)
        function_name: os.environ/DECIDER_GUARD_FUNCTION
        region: ap-northeast-2
        # decider_url: http://10.0.0.12:8000   (backend: http; guard_core.py must sit next to this file)
        block_on_ask: true
        fail_mode: closed          # closed: reject when the guard is unreachable
        language: en               # en | ko (error messages and reasons)
"""
import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Any, Optional

from fastapi import HTTPException
from litellm.integrations.custom_guardrail import CustomGuardrail

SEVERITY = {"allow": 0, "ask": 1, "block": 2}
MESSAGES = {
    "en": {"blocked": "Sensitive data was detected and the request was blocked. Mask or remove it and try again.",
           "unavailable": "guard unavailable"},
    "ko": {"blocked": "민감 정보가 감지되어 요청을 차단했습니다. 마스킹하거나 해당 데이터를 제외하고 다시 시도하세요.",
           "unavailable": "guard 에 연결할 수 없습니다"},
}


def _texts_from_content(content) -> list:
    """Text out of OpenAI / Anthropic / Responses content (string or list of blocks)."""
    if content is None:
        return []
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, dict):
        content = [content]
    for block in content if isinstance(content, list) else []:
        if isinstance(block, str):
            out.append(block)
        elif isinstance(block, dict):
            for key in ("text", "input_text", "output"):
                if isinstance(block.get(key), str):
                    out.append(block[key])
            if "content" in block:                      # anthropic tool_result
                out += _texts_from_content(block["content"])
            if block.get("type") in ("tool_use", "function_call") and block.get("input" if "input" in block else "arguments"):
                v = block.get("input", block.get("arguments"))
                out.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    return out


def newest_turn(data: dict) -> list:
    """[(source, text)] for the messages after the last assistant message."""
    items = []
    msgs = data.get("messages")
    if isinstance(msgs, list) and msgs:
        tail = []
        for m in reversed(msgs):
            if not isinstance(m, dict):
                continue
            if m.get("role") == "assistant":
                break
            tail.append(m)
        for m in reversed(tail):
            if m.get("role") in ("system", "developer"):
                continue
            src = "tool_result" if m.get("role") == "tool" or _has_tool_result(m) else m.get("role", "user")
            items += [(src, t) for t in _texts_from_content(m.get("content"))]
    inp = data.get("input")                             # Responses API
    if isinstance(inp, str):
        items.append(("user", inp))
    elif isinstance(inp, list):
        tail = []
        for it in reversed(inp):
            if isinstance(it, dict) and it.get("role") == "assistant":
                break
            tail.append(it)
        for it in reversed(tail):
            if not isinstance(it, dict) or it.get("role") in ("system", "developer"):
                continue
            if it.get("type") == "function_call_output":
                items.append(("tool_result", it.get("output") if isinstance(it.get("output"), str) else json.dumps(it.get("output"), ensure_ascii=False)))
            elif it.get("type") == "function_call":
                continue  # model's own call; its arguments were produced from already-checked context
            else:
                items += [("user", t) for t in _texts_from_content(it.get("content"))]
    return [(s, t) for s, t in items if t and t.strip()]


def _has_tool_result(m) -> bool:
    c = m.get("content")
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


class DeciderGuardrail(CustomGuardrail):
    def __init__(self, backend: str = "lambda", function_name: Optional[str] = None, region: Optional[str] = None,
                 decider_url: Optional[str] = None, block_on_ask: Any = True, fail_mode: str = "closed",
                 language: str = "en", **kwargs):
        self.backend = backend
        self.function_name = function_name
        self.region = region
        self.decider_url = decider_url
        self.block_on_ask = str(block_on_ask).lower() not in ("false", "0", "no")
        self.fail_mode = fail_mode
        self.language = "ko" if language == "ko" else "en"
        self._passed = OrderedDict()   # sha256 -> None, LRU of texts that already passed
        self._lambda = None
        super().__init__(**kwargs)

    # ---- backend ----
    def _check_sync(self, items):
        if self.backend == "http":
            import guard_core
            return guard_core.check_many(items, self.decider_url, lang=self.language)
        if self._lambda is None:
            import boto3
            from botocore.config import Config
            self._lambda = boto3.client("lambda", region_name=self.region, config=Config(read_timeout=30, retries={"max_attempts": 2}))
        resp = self._lambda.invoke(FunctionName=self.function_name, Payload=json.dumps({"items": items, "client": "litellm", "lang": self.language}).encode())
        out = json.load(resp["Payload"])
        if resp.get("FunctionError"):
            raise RuntimeError(out.get("errorMessage", str(out)))
        return out

    def _remember(self, h):
        self._passed[h] = None
        self._passed.move_to_end(h)
        while len(self._passed) > 5000:
            self._passed.popitem(last=False)

    # ---- hook ----
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        pairs = newest_turn(data)
        fresh = []
        for src, text in pairs:
            h = hashlib.sha256(text.encode()).hexdigest()
            if h not in self._passed:
                fresh.append((h, {"source": src, "text": text}))
        if not fresh:
            return data
        try:
            verdict = await asyncio.to_thread(self._check_sync, [it for _, it in fresh])
        except Exception as e:
            if self.fail_mode == "closed":
                raise HTTPException(status_code=503, detail={"error": f"[PII guard] {MESSAGES[self.language]['unavailable']}: {str(e)[:200]}"})
            return data
        decision = verdict["decision"]
        if decision == "ask" and not self.block_on_ask:
            decision = "allow"
        if decision == "allow":
            for h, _ in fresh:
                self._remember(h)
            return data
        reasons = [f"[{r['source']}] {x}" for r in verdict.get("results", []) if r["decision"] != "allow" for x in r.get("reasons", [])]
        raise HTTPException(status_code=400, detail={
            "error": f"[PII guard] {verdict.get('message') or MESSAGES[self.language]['blocked']}",
            "decision": verdict["decision"],
            "reasons": reasons[:8],
        })
