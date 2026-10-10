"""Admin API for the policy console (API Gateway HTTP API + Cognito JWT, or admin/dev_server.py locally).

  GET  /api/policy                 current policy + category/sensitivity metadata
  PUT  /api/policy                 {"policy": {...}} -> validate and save (new version)
  POST /api/test                   {"text": "...", "policy": {...draft}} -> verdict with the draft policy
  GET  /api/history                saved versions (newest first)
  GET  /api/history/{version_id}   one saved version
  GET  /api/stats?hours=24         decision counts and recent blocks (no raw text exists to show)

AWS mode: POLICY_BUCKET/POLICY_KEY (versioned S3), GUARD_FUNCTION (dry-run tests), GUARD_LOG_GROUP (stats).
Local mode (dev_server.py): POLICY_FILE, LOCAL_DECIDER_URL and AUDIT_LOG instead.
"""
import base64
import datetime as dt
import json
import os
import time

import guard_core

POLICY_BUCKET = os.environ.get("POLICY_BUCKET")
POLICY_KEY = os.environ.get("POLICY_KEY", "policy.json")
GUARD_FUNCTION = os.environ.get("GUARD_FUNCTION")
GUARD_LOG_GROUP = os.environ.get("GUARD_LOG_GROUP")
POLICY_FILE = os.environ.get("POLICY_FILE")
LOCAL_DECIDER_URL = os.environ.get("LOCAL_DECIDER_URL")
AUDIT_LOG = os.environ.get("AUDIT_LOG")
MAX_TEST_CHARS = 20000

_clients = {}


def _aws(name):
    if name not in _clients:
        import boto3
        _clients[name] = boto3.client(name)
    return _clients[name]


def meta():
    return {
        "categories": [{k: c[k] for k in ("id", "label", "desc")} for c in guard_core.CATEGORIES],
        "sensitivities": [{"id": k, "label": v} for k, v in guard_core.SENSITIVITY_LABELS.items()],
        "labels": guard_core.LABELS,
        "limits": guard_core.LIMITS,
    }


# ---------- storage ----------

def load_policy(version_id=None):
    if POLICY_FILE:
        try:
            with open(POLICY_FILE) as f:
                return guard_core.normalize_policy(json.load(f)), "local"
        except FileNotFoundError:
            return guard_core.normalize_policy(None), None
    try:
        kw = {"Bucket": POLICY_BUCKET, "Key": POLICY_KEY}
        if version_id:
            kw["VersionId"] = version_id
        obj = _aws("s3").get_object(**kw)
        return guard_core.normalize_policy(json.load(obj["Body"])), obj.get("VersionId")
    except _aws("s3").exceptions.NoSuchKey:
        return guard_core.normalize_policy(None), None


def save_policy(policy, user):
    policy = guard_core.normalize_policy(policy)
    policy["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    policy["updated_by"] = user
    body = json.dumps(policy, ensure_ascii=False, indent=2).encode()
    if POLICY_FILE:
        os.makedirs(os.path.dirname(POLICY_FILE) or ".", exist_ok=True)
        hist = POLICY_FILE + ".history.jsonl"
        with open(hist, "a") as f:
            f.write(json.dumps(policy, ensure_ascii=False) + "\n")
        with open(POLICY_FILE, "wb") as f:
            f.write(body)
        return policy, "local"
    user_meta = user.encode("ascii", "replace").decode()[:100]
    resp = _aws("s3").put_object(Bucket=POLICY_BUCKET, Key=POLICY_KEY, Body=body, ContentType="application/json",
                                 Metadata={"updated-by": user_meta})
    return policy, resp.get("VersionId")


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
    vs = _aws("s3").list_object_versions(Bucket=POLICY_BUCKET, Prefix=POLICY_KEY, MaxKeys=30).get("Versions", [])
    out = []
    for v in sorted((v for v in vs if v["Key"] == POLICY_KEY), key=lambda v: v["LastModified"], reverse=True)[:30]:
        head = _aws("s3").head_object(Bucket=POLICY_BUCKET, Key=POLICY_KEY, VersionId=v["VersionId"])
        out.append({"version_id": v["VersionId"], "saved_at": v["LastModified"].isoformat(timespec="seconds"),
                    "by": head.get("Metadata", {}).get("updated-by"), "current": v.get("IsLatest", False)})
    return out


def history_version(version_id):
    if POLICY_FILE:
        i = int(version_id.split("-", 1)[1])
        with open(POLICY_FILE + ".history.jsonl") as f:
            return guard_core.normalize_policy(json.loads(f.readlines()[i]))
    return load_policy(version_id)[0]


# ---------- test & stats ----------

def run_test(text, policy):
    policy = guard_core.normalize_policy(policy)
    items = [{"source": "test", "text": text[:MAX_TEST_CHARS]}]
    if LOCAL_DECIDER_URL or not GUARD_FUNCTION:
        return guard_core.check_many(items, LOCAL_DECIDER_URL, policy)
    resp = _aws("lambda").invoke(FunctionName=GUARD_FUNCTION,
                                 Payload=json.dumps({"items": items, "policy": policy, "dry_run": True, "client": "console"}).encode())
    out = json.load(resp["Payload"])
    if resp.get("FunctionError"):
        raise RuntimeError(out.get("errorMessage", "guard error"))
    return out


def stats(hours):
    if AUDIT_LOG:
        return _local_stats(hours)
    logs = _aws("logs")
    end = int(time.time())
    start = end - hours * 3600
    queries = {
        "by_decision": "filter ispresent(decision) and client != 'status' | stats count(*) as n by decision",
        "by_category": "filter decision != 'allow' | stats count(*) as n by categories | sort n desc | limit 20",
        "by_client": "filter ispresent(decision) | stats count(*) as n by client | sort n desc | limit 10",
        "recent": "filter decision != 'allow' | sort @timestamp desc | limit 25 | fields @timestamp, decision, client, sources, categories, ms",
    }
    ids = {k: logs.start_query(logGroupName=GUARD_LOG_GROUP, startTime=start, endTime=end, queryString=q)["queryId"] for k, q in queries.items()}
    results = {}
    deadline = time.time() + 20
    while ids and time.time() < deadline:
        time.sleep(0.7)
        for k in list(ids):
            r = logs.get_query_results(queryId=ids[k])
            if r["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
                results[k] = [{f["field"]: f["value"] for f in row if not f["field"].startswith("@ptr")} for row in r.get("results", [])]
                del ids[k]
    for k in ids:
        results[k] = []
    counts = {r.get("decision"): int(r.get("n", 0)) for r in results["by_decision"]}
    return {
        "hours": hours,
        "total": sum(counts.values()), "block": counts.get("block", 0), "ask": counts.get("ask", 0),
        "by_category": _split_counts(results["by_category"], "categories"),
        "by_client": [{"key": r.get("client") or "-", "n": int(r.get("n", 0))} for r in results["by_client"]],
        "recent": [{"ts": (r.get("@timestamp") or "").replace(" ", "T") + "Z", "decision": r.get("decision"), "client": r.get("client"),
                    "sources": r.get("sources"), "categories": r.get("categories"), "ms": r.get("ms")} for r in results["recent"]],
        "partial": bool(ids),
    }


def _split_counts(rows, field):
    """'contact,health' rows -> per-category counts."""
    agg = {}
    for r in rows:
        for c in (r.get(field) or "").split(","):
            if c:
                agg[c] = agg.get(c, 0) + int(r.get("n", 0))
    return [{"key": k, "n": n} for k, n in sorted(agg.items(), key=lambda kv: -kv[1])]


def _local_stats(hours):
    since = dt.datetime.now() - dt.timedelta(hours=hours)
    rows = []
    try:
        with open(AUDIT_LOG) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if dt.datetime.fromisoformat(e["ts"]) >= since:
                        rows.append(e)
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        pass
    cat = {p: c for p, c in guard_core.CATEGORY_OF_PATTERN.items()} | dict(guard_core.CATEGORY_OF_KIND)
    def cats(e):
        return ",".join(sorted({cat.get(t, t) for t in e.get("types", [])}))
    blocked = [e for e in rows if e["decision"] != "allow"]
    by_client = {}
    for e in rows:
        by_client[e["agent"]] = by_client.get(e["agent"], 0) + 1
    return {
        "hours": hours, "total": len(rows),
        "block": sum(e["decision"] == "block" for e in rows), "ask": sum(e["decision"] == "ask" for e in rows),
        "by_category": _split_counts([{"categories": cats(e), "n": 1} for e in blocked], "categories"),
        "by_client": [{"key": k, "n": n} for k, n in sorted(by_client.items(), key=lambda kv: -kv[1])],
        "recent": [{"ts": e["ts"], "decision": e["decision"], "client": e["agent"], "sources": ",".join(e.get("sources", [])),
                    "categories": cats(e), "ms": e.get("ms")} for e in blocked[::-1][:25]],
        "partial": False,
    }


# ---------- HTTP ----------

def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _user(event):
    claims = (event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}) or {}).get("claims", {})
    return claims.get("email") or claims.get("cognito:username") or "local-admin"


def handler(event, context=None):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        return _resp(400, {"error": "JSON 형식이 아닙니다"})
    try:
        if path == "/api/policy" and method == "GET":
            policy, version = load_policy()
            return _resp(200, {"policy": policy, "version_id": version, "meta": meta()})
        if path == "/api/policy" and method == "PUT":
            policy, version = save_policy(body.get("policy"), _user(event))
            return _resp(200, {"policy": policy, "version_id": version})
        if path == "/api/test" and method == "POST":
            text = str(body.get("text") or "")
            if not text.strip():
                return _resp(400, {"error": "검사할 텍스트를 입력하세요"})
            return _resp(200, run_test(text, body.get("policy")))
        if path == "/api/history" and method == "GET":
            return _resp(200, {"versions": history()})
        if path.startswith("/api/history/") and method == "GET":
            return _resp(200, {"policy": history_version(path.rsplit("/", 1)[1])})
        if path == "/api/stats" and method == "GET":
            hours = int((event.get("queryStringParameters") or {}).get("hours", "24"))
            return _resp(200, stats(max(1, min(hours, 24 * 30))))
        return _resp(404, {"error": "not found"})
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    except Exception as e:
        print(json.dumps({"error": repr(e)[:500], "path": path}))
        return _resp(500, {"error": f"서버 오류: {str(e)[:200]}"})
