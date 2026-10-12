"""Lambda entry point.

  {"items": [{"source", "text"}], "client": "claude", "lang": "en"}   -> verdict under the saved policy
      optional "user": who the caller acts for (the LiteLLM guardrail sends the key's user); logged with
      user_source "caller", since a direct invoke cannot prove it
  {"items": [...], "policy": {...}, "dry_run": true}    -> verdict under a draft policy (admin console test; not logged)
  {"health": true}                                      -> decider status

Also served as POST /guard/check behind an API Gateway JWT authorizer (hooks with --auth jwt): the body is the first or
third form, the signed-in user (from the token) is logged with user_source "token", and draft policies are refused.

The policy is read from S3 (POLICY_BUCKET/POLICY_KEY, saved by the admin console) and cached
for 30 s; a missing policy means the defaults. Logs only decisions, sources, categories and
sizes, never the text itself.
"""
import base64
import json
import logging
import os
import time

import guard_core

log = logging.getLogger()
log.setLevel(logging.INFO)

POLICY_BUCKET = os.environ.get("POLICY_BUCKET")
EVIDENCE_BUCKET = os.environ.get("EVIDENCE_BUCKET")   # opt-in text capture (policy "evidence"), expires by lifecycle rule
EVIDENCE_CHARS = 4000
POLICY_KEY = os.environ.get("POLICY_KEY", "policy.json")
POLICY_TTL = 30
MAX_API_BYTES = 2_000_000   # per request through the API (the hook sends at most ~256 KB per file)
_cache = {"at": 0.0, "policy": None}


def current_policy():
    if not POLICY_BUCKET:
        return guard_core.normalize_policy(None)
    if _cache["policy"] is not None and time.time() - _cache["at"] < POLICY_TTL:
        return _cache["policy"]
    import boto3
    s3 = boto3.client("s3")
    try:
        policy = guard_core.normalize_policy(json.load(s3.get_object(Bucket=POLICY_BUCKET, Key=POLICY_KEY)["Body"]))
    except s3.exceptions.NoSuchKey:
        policy = guard_core.normalize_policy(None)
    except Exception as e:  # keep enforcing the last good policy rather than failing open
        log.error(json.dumps({"policy_load_error": repr(e)[:300]}))
        policy = _cache["policy"] or guard_core.normalize_policy(None)
    _cache.update(at=time.time(), policy=policy)
    return policy


def overall_basis(out):
    return next((r.get("basis") for r in out["results"] if r["decision"] == out["decision"] and r.get("basis")), None)


def save_evidence(items, out, policy, client, request_id, user=""):
    """Store the checked text when the policy asks for it. Returns the S3 key (logged; the text itself never is)."""
    mode = policy.get("evidence", "off")
    if mode == "off" or not EVIDENCE_BUCKET or (mode == "blocked" and out["decision"] == "allow"):
        return None
    import boto3
    key = f"evidence/{time.strftime('%Y/%m/%d', time.gmtime())}/{request_id}.json"
    body = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "client": client, "user": user, "decision": out["decision"],
            "items": [{"source": i.get("source", ""), "text": i.get("text", "")[:EVIDENCE_CHARS],
                       "truncated": len(i.get("text", "")) > EVIDENCE_CHARS, "decision": r["decision"], "basis": r.get("basis"),
                       "reasons": r.get("reasons", [])} for i, r in zip(items, out["results"])]}
    boto3.client("s3").put_object(Bucket=EVIDENCE_BUCKET, Key=key, Body=json.dumps(body, ensure_ascii=False).encode(),
                                  ContentType="application/json")
    return key


def _categories(result):
    cats = set()
    for r in result["results"]:
        for f in r["findings"]:
            cats.add(f"rule:{f['name']}" if f["source"] == "rule" else f.get("category", f["type"]))
    return ",".join(sorted(cats))


def _api_response(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body, ensure_ascii=False)}


def api_handler(event, context):
    """POST /guard/check (API Gateway HTTP API, payload v2). The authorizer has already verified the token."""
    claims = ((event["requestContext"].get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    user = claims.get("email") or claims.get("cognito:username") or claims.get("sub") or ""
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
    if len(raw) > MAX_API_BYTES:
        return _api_response(413, {"error": "request too large"})
    try:
        body = json.loads(raw)
        items = body.get("items") if "items" in body else [{"source": body.get("source", ""), "text": body.get("text", "")}]
        if not body.get("health") and not (isinstance(items, list) and 0 < len(items) <= 50
                                           and all(isinstance(i, dict) and isinstance(i.get("text", ""), str) for i in items)):
            raise ValueError("items must be a list of 1-50 {source, text} objects")
    except (ValueError, AttributeError) as e:
        return _api_response(400, {"error": str(e)[:200]})
    if body.get("health"):
        return _api_response(200, handler({"health": True}, context))
    # Only the admin console (IAM invoke) may test draft policies; developers always get the saved policy.
    return _api_response(200, check({"items": items, "client": str(body.get("client", ""))[:20], "lang": body.get("lang")}, context,
                                    user, "token" if user else ""))


def handler(event, context):
    if "http" in (event.get("requestContext") or {}):
        return api_handler(event, context)
    if event.get("health"):
        try:
            return {"ok": True, "decider": guard_core.health()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    user = str(event.get("user") or "")[:200]
    return check(event, context, user, "caller" if user else "")


def check(event, context, user="", user_source=""):
    """user_source: "token" (verified by the API's JWT authorizer) or "caller" (reported by an IAM caller such as LiteLLM)."""
    dry_run = bool(event.get("dry_run"))
    lang = guard_core.lang_of(event.get("lang"))
    policy = guard_core.normalize_policy(event["policy"], lang) if dry_run and "policy" in event else current_policy()
    items = event.get("items") or [{"source": event.get("source", ""), "text": event.get("text", "")}]
    t0 = time.time()
    out = guard_core.check_many(items, policy=policy, lang=lang)
    out["policy_updated_at"] = policy.get("updated_at")
    out["basis"] = overall_basis(out)
    if not dry_run:
        try:
            out["evidence"] = save_evidence(items, out, policy, event.get("client", ""), getattr(context, "aws_request_id", None) or str(time.time()), user)
        except Exception as e:  # never fail a check because the evidence copy failed
            log.error(json.dumps({"evidence_error": repr(e)[:300]}))
            out["evidence"] = None
        # A bare JSON line (not logging's "[INFO] ts id ..." prefix) so CloudWatch metric filters can match on fields.
        print(json.dumps({
            "decision": out["decision"],
            "client": event.get("client", ""),
            "user": user,
            "user_source": user_source,
            "sources": ",".join(r["source"] for r in out["results"]),
            "categories": _categories(out),
            "basis": out["basis"] or "",
            "evidence": out.get("evidence") or "",
            "chars": sum(len(i.get("text", "")) for i in items),
            "ms": round((time.time() - t0) * 1000),
        }, ensure_ascii=False), flush=True)
    return out
