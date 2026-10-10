"""Lambda entry point: {"items": [{"source", "text"}]} or {"text": ...} -> guard verdict; {"health": true} -> decider status.

Logs only decisions, sources, finding types and sizes, never the text itself.
"""
import json
import logging

import guard_core

log = logging.getLogger()
log.setLevel(logging.INFO)


def handler(event, context):
    if event.get("health"):
        try:
            return {"ok": True, "decider": guard_core.health()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    items = event.get("items") or [{"source": event.get("source", ""), "text": event.get("text", "")}]
    out = guard_core.check_many(items)
    log.info(json.dumps({
        "decision": out["decision"],
        "client": event.get("client", ""),
        "items": [{"source": r["source"], "decision": r["decision"], "types": sorted({f["type"] for f in r["findings"]}),
                   "chunks": r["chunks_scanned"], "ms": r["latency_ms"]} for r in out["results"]],
        "chars": [len(i.get("text", "")) for i in items],
    }, ensure_ascii=False))
    return out
