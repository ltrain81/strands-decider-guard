"""Admin API for the policy console (API Gateway HTTP API + Cognito JWT, or admin/dev_server.py locally).

  GET  /api/policy                  current policy + category/sensitivity metadata
  PUT  /api/policy                  {"policy": {...}} -> validate, save a new version, log who changed what
  POST /api/test                    {"text", "policy"} -> verdict under a draft policy (not logged)
  GET  /api/history                 saved versions, newest first
  GET  /api/history/{version}       one version + what differs from the current policy
  GET  /api/overview?hours=24       health, KPIs and time series (monitoring.py)
  GET  /api/logs?hours&decision&client&category&q&limit   decision log search (no text exists to show)
  GET  /api/activity?hours=168      admin actions: policy and alert changes
  GET  /api/alerts                  alert settings, email subscription and alarm states (alerts.py)
  PUT  /api/alerts                  {"alerts": {...}} -> save and apply
  POST /api/alerts/test             send a test notification

Also invoked by a 5-minute EventBridge schedule ({"health_check": true}) to publish the guard health metric.
Modes and settings: see common.py.
"""
import base64
import datetime as dt
import json
import os

import alerts
import guard_core
import monitoring
from common import GUARD_FUNCTION, LOCAL_DECIDER_URL, POLICY_BUCKET, POLICY_FILE, POLICY_KEY, aws

MAX_TEST_CHARS = 20000
MESSAGES = {
    "en": {"bad_json": "The request body is not valid JSON", "no_text": "Enter some text to check", "server": "Server error: {e}"},
    "ko": {"bad_json": "JSON 형식이 아닙니다", "no_text": "검사할 텍스트를 입력하세요", "server": "서버 오류: {e}"},
}


def meta(lang):
    return {
        "categories": [{"id": c["id"], "label": c["label"][lang], "desc": c["desc"][lang]} for c in guard_core.CATEGORIES],
        "sensitivities": [{"id": k, "label": v} for k, v in guard_core.SENSITIVITY_LABELS[lang].items()],
        "labels": guard_core.PATTERN_LABELS[lang],
        "limits": guard_core.LIMITS,
        "local": bool(POLICY_FILE),
    }


def audit(action, user, detail=None):
    """One JSON line per admin action; the Logs tab's "admin activity" reads these back."""
    print(json.dumps({"action": action, "by": user, "detail": detail}, ensure_ascii=False), flush=True)


# ---------- policy storage ----------

def load_policy(version_id=None):
    if POLICY_FILE:
        try:
            with open(POLICY_FILE) as f:
                return guard_core.normalize_policy(json.load(f)), "local"
        except FileNotFoundError:
            return guard_core.normalize_policy(None), None
    s3 = aws("s3")
    try:
        kw = {"Bucket": POLICY_BUCKET, "Key": POLICY_KEY}
        if version_id:
            kw["VersionId"] = version_id
        obj = s3.get_object(**kw)
        return guard_core.normalize_policy(json.load(obj["Body"])), obj.get("VersionId")
    except s3.exceptions.NoSuchKey:
        return guard_core.normalize_policy(None), None


def save_policy(policy, user, lang="en"):
    old, _ = load_policy()
    policy = guard_core.normalize_policy(policy, lang)
    policy["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    policy["updated_by"] = user
    body = json.dumps(policy, ensure_ascii=False, indent=2).encode()
    if POLICY_FILE:
        os.makedirs(os.path.dirname(POLICY_FILE) or ".", exist_ok=True)
        with open(POLICY_FILE + ".history.jsonl", "a") as f:
            f.write(json.dumps(policy, ensure_ascii=False) + "\n")
        with open(POLICY_FILE, "wb") as f:
            f.write(body)
        version = "local"
    else:
        resp = aws("s3").put_object(Bucket=POLICY_BUCKET, Key=POLICY_KEY, Body=body, ContentType="application/json",
                                    Metadata={"updated-by": user.encode("ascii", "replace").decode()[:100]})
        version = resp.get("VersionId")
    audit("policy_saved", user, monitoring.policy_changes(old, policy))
    return policy, version


def history():
    if POLICY_FILE:
        out = []
        try:
            with open(POLICY_FILE + ".history.jsonl") as f:
                for i, line in enumerate(f):
                    p = json.loads(line)
                    out.append({"version_id": f"local-{i}", "saved_at": p.get("updated_at"), "by": p.get("updated_by")})
        except FileNotFoundError:
            pass
        return out[::-1][:30]
    s3 = aws("s3")
    vs = s3.list_object_versions(Bucket=POLICY_BUCKET, Prefix=POLICY_KEY, MaxKeys=30).get("Versions", [])
    out = []
    for v in sorted((v for v in vs if v["Key"] == POLICY_KEY), key=lambda v: v["LastModified"], reverse=True)[:30]:
        head = s3.head_object(Bucket=POLICY_BUCKET, Key=POLICY_KEY, VersionId=v["VersionId"])
        out.append({"version_id": v["VersionId"], "saved_at": v["LastModified"].isoformat(timespec="seconds"),
                    "by": head.get("Metadata", {}).get("updated-by"), "current": v.get("IsLatest", False)})
    return out


def history_version(version_id):
    if POLICY_FILE:
        i = int(version_id.split("-", 1)[1])
        with open(POLICY_FILE + ".history.jsonl") as f:
            policy = guard_core.normalize_policy(json.loads(f.readlines()[i]))
    else:
        policy = load_policy(version_id)[0]
    current, _ = load_policy()
    return {"policy": policy, "changes": monitoring.policy_changes(current, policy)}  # what loading it would change


def run_test(text, policy, lang="en"):
    policy = guard_core.normalize_policy(policy, lang)
    items = [{"source": "test", "text": text[:MAX_TEST_CHARS]}]
    if LOCAL_DECIDER_URL or not GUARD_FUNCTION:
        return guard_core.check_many(items, LOCAL_DECIDER_URL, policy, lang)
    resp = aws("lambda").invoke(FunctionName=GUARD_FUNCTION, Payload=json.dumps(
        {"items": items, "policy": policy, "dry_run": True, "client": "console", "lang": lang}).encode())
    out = json.load(resp["Payload"])
    if resp.get("FunctionError"):
        raise RuntimeError(out.get("errorMessage", "guard error"))
    return out


# ---------- HTTP ----------

def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _user(event):
    claims = (event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}) or {}).get("claims", {})
    return claims.get("email") or claims.get("cognito:username") or "local-admin"


def _hours(q, default):
    return max(1, min(int(q.get("hours", default)), 24 * 30))


def route(method, path, body, q, user, lang):
    if path == "/api/policy" and method == "GET":
        policy, version = load_policy()
        return {"policy": policy, "version_id": version, "meta": meta(lang)}
    if path == "/api/policy" and method == "PUT":
        policy, version = save_policy(body.get("policy"), user, lang)
        return {"policy": policy, "version_id": version}
    if path == "/api/test" and method == "POST":
        text = str(body.get("text") or "")
        if not text.strip():
            raise ValueError(MESSAGES[lang]["no_text"])
        return run_test(text, body.get("policy"), lang)
    if path == "/api/history" and method == "GET":
        return {"versions": history()}
    if path.startswith("/api/history/") and method == "GET":
        return history_version(path.rsplit("/", 1)[1])
    if path == "/api/overview" and method == "GET":
        return monitoring.overview(_hours(q, "24"), load_policy()[0])
    if path == "/api/logs" and method == "GET":
        return monitoring.decision_log(q)
    if path == "/api/activity" and method == "GET":
        return monitoring.admin_activity(_hours(q, "168"))
    if path == "/api/alerts" and method == "GET":
        return alerts.status()
    if path == "/api/alerts" and method == "PUT":
        cfg, changes = alerts.save(body.get("alerts"))
        audit("alerts_saved", user, changes)
        return alerts.status()
    if path == "/api/alerts/test" and method == "POST":
        alerts.send_test(user)
        audit("alert_test", user)
        return {"sent": True}
    return None


def handler(event, context=None):
    if event.get("health_check"):  # EventBridge schedule
        return alerts.health_check()
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    lang = guard_core.lang_of((event.get("headers") or {}).get("x-lang"))
    path = event.get("rawPath", "")
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        return _resp(400, {"error": MESSAGES[lang]["bad_json"]})
    try:
        out = route(method, path, body, event.get("queryStringParameters") or {}, _user(event), lang)
        return _resp(200, out) if out is not None else _resp(404, {"error": "not found"})
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    except Exception as e:
        print(json.dumps({"error": repr(e)[:500], "path": path}))
        return _resp(500, {"error": MESSAGES[lang]["server"].format(e=str(e)[:200])})
