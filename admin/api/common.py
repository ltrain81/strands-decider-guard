"""Shared settings and helpers for the admin API modules.

Two modes:
  AWS    POLICY_BUCKET, GUARD_FUNCTION, GUARD_LOG_GROUP, ADMIN_LOG_GROUP, ALERTS_TOPIC, ... (set by the CDK stack)
  local  POLICY_FILE, LOCAL_DECIDER_URL, AUDIT_LOG (set by admin/dev_server.py; no AWS calls at all)
"""
import datetime as dt
import json
import os
import time

import guard_core

env = os.environ.get
POLICY_BUCKET = env("POLICY_BUCKET")
POLICY_KEY = env("POLICY_KEY", "policy.json")
ALERTS_KEY = env("ALERTS_KEY", "alerts.json")
GUARD_FUNCTION = env("GUARD_FUNCTION")
GUARD_LOG_GROUP = env("GUARD_LOG_GROUP")
ADMIN_LOG_GROUP = env("ADMIN_LOG_GROUP")
GUARD_INSTANCE_ID = env("GUARD_INSTANCE_ID")
ALERTS_TOPIC = env("ALERTS_TOPIC")
ALARM_PREFIX = env("ALARM_PREFIX", "DeciderGuard-")
METRIC_NAMESPACE = env("METRIC_NAMESPACE", "DeciderGuard")
SCHEDULE = env("SCHEDULE", "")                      # e.g. "MON-FRI 08:00-20:00" (host auto start/stop), empty = always on
SCHEDULE_UTC_OFFSET = float(env("SCHEDULE_UTC_OFFSET", "9"))
POLICY_FILE = env("POLICY_FILE")
LOCAL_DECIDER_URL = env("LOCAL_DECIDER_URL")
AUDIT_LOG = env("AUDIT_LOG")
LOCAL = bool(POLICY_FILE)

_clients = {}


def aws(name):
    if name not in _clients:
        import boto3
        _clients[name] = boto3.client(name)
    return _clients[name]


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def in_schedule(when=None):
    """True when the host is meant to be running (always true without a schedule)."""
    if not SCHEDULE:
        return True
    days, hours = SCHEDULE.split()
    d1, d2 = days.split("-")
    (h1, m1), (h2, m2) = (map(int, x.split(":")) for x in hours.split("-"))
    local = (when or now_utc()) + dt.timedelta(hours=SCHEDULE_UTC_OFFSET)
    if not DAYS.index(d1) <= local.weekday() <= DAYS.index(d2):
        return False
    minutes = local.hour * 60 + local.minute
    return h1 * 60 + m1 <= minutes < h2 * 60 + m2


def bin_for(hours):
    """Chart bucket size for a period: (Logs Insights bin, seconds)."""
    if hours <= 1:
        return "5m", 300
    if hours <= 24:
        return "1h", 3600
    if hours <= 24 * 7:
        return "6h", 21600
    return "1d", 86400


def insights(log_group, queries, hours, timeout=20):
    """Run several Logs Insights queries in parallel -> ({name: [row dict]}, partial)."""
    logs = aws("logs")
    end = int(time.time())
    start = end - hours * 3600
    ids = {k: logs.start_query(logGroupName=log_group, startTime=start, endTime=end, queryString=q)["queryId"] for k, q in queries.items()}
    results, deadline = {}, time.time() + timeout
    while ids and time.time() < deadline:
        time.sleep(0.6)
        for k in list(ids):
            r = logs.get_query_results(queryId=ids[k])
            if r["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
                results[k] = [{f["field"]: f["value"] for f in row if not f["field"].startswith("@ptr")} for row in r.get("results", [])]
                del ids[k]
    for k in ids:
        results[k] = []
    return results, bool(ids)


def iso_from_insights(ts):
    """'2026-10-11 14:43:23.123' (UTC) -> '2026-10-11T14:43:23.123Z'."""
    return (ts or "").replace(" ", "T") + ("Z" if ts and not ts.endswith("Z") else "")


# ---------- local mode: the hook's audit.log stands in for the guard's CloudWatch log ----------

CATEGORY_OF_TYPE = dict(guard_core.CATEGORY_OF_PATTERN) | dict(guard_core.CATEGORY_OF_KIND)


def local_events(hours):
    """Decision events from the local audit.log, shaped like the guard Lambda's log lines."""
    since = dt.datetime.now() - dt.timedelta(hours=hours)
    out = []
    try:
        with open(AUDIT_LOG) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = dt.datetime.fromisoformat(e["ts"])
                except (ValueError, KeyError):
                    continue
                if ts < since:
                    continue
                out.append({
                    "ts": ts.astimezone().isoformat(timespec="seconds"),
                    "_t": ts.timestamp(),
                    "decision": e.get("decision"),
                    "client": e.get("agent", ""),
                    "tool": e.get("tool") or ("prompt" if e.get("event") == "UserPromptSubmit" else ""),
                    "sources": ",".join(e.get("sources", [])),
                    "categories": ",".join(sorted({CATEGORY_OF_TYPE.get(t, t) for t in e.get("types", [])})),
                    "ms": e.get("ms"),
                })
    except FileNotFoundError:
        pass
    return out


def percentile(values, p):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)
