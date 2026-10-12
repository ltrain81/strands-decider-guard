"""Monitoring for the console: overview (health, KPIs, time series), the decision log, and admin activity.

Everything comes from what the guard already logs (decision, client, sources, categories, chars, ms),
so no request text is ever available here. AWS mode reads CloudWatch; local mode reads audit.log.
"""
import json
import re
import time

import guard_core
from common import (ADMIN_LOG_GROUP, ALARM_PREFIX, GUARD_FUNCTION, GUARD_INSTANCE_ID, GUARD_LOG_GROUP, LOCAL,
                    LOCAL_DECIDER_URL, POLICY_FILE, SCHEDULE, SCHEDULE_UTC_OFFSET, aws, bin_for, in_schedule, insights,
                    iso_from_insights, local_events, percentile)

DECISIONS = ("allow", "ask", "block")
SAFE = re.compile(r"^[\w.\-:/ ,@가-힣]{0,80}$")


# ---------- policy diff (also used by handler.py for the audit log and the history view) ----------

def policy_changes(old, new):
    """Structured list of differences; the console renders them in the reader's language."""
    old, new = old or guard_core.normalize_policy(None), new or guard_core.normalize_policy(None)
    out = []
    if old["sensitivity"] != new["sensitivity"]:
        out.append({"kind": "sensitivity", "from": old["sensitivity"], "to": new["sensitivity"]})
    for cid, action in new["categories"].items():
        if old["categories"].get(cid) != action:
            out.append({"kind": "category", "id": cid, "from": old["categories"].get(cid), "to": action})
    old_rules = {r["id"]: r for r in old["custom_rules"]}
    new_rules = {r["id"]: r for r in new["custom_rules"]}
    for rid, r in new_rules.items():
        if rid not in old_rules:
            out.append({"kind": "rule_added", "name": r["name"]})
        else:
            fields = [k for k in ("name", "question", "action", "sensitivity", "enabled") if old_rules[rid][k] != r[k]]
            if fields:
                out.append({"kind": "rule_changed", "name": r["name"], "fields": fields})
    for rid, r in old_rules.items():
        if rid not in new_rules:
            out.append({"kind": "rule_removed", "name": r["name"]})
    for key in ("email_domains", "terms"):
        a, b = set(old["allow"][key]), set(new["allow"][key])
        for v in sorted(b - a):
            out.append({"kind": "allow_added", "list": key, "value": v})
        for v in sorted(a - b):
            out.append({"kind": "allow_removed", "list": key, "value": v})
    if (old.get("message") or "") != (new.get("message") or ""):
        out.append({"kind": "message"})
    for key in ("patterns", "evidence"):
        if old.get(key) != new.get(key):
            out.append({"kind": key, "from": old.get(key), "to": new.get(key)})
    return out


# ---------- health ----------

def guard_health():
    try:
        if LOCAL:
            d = guard_core.health(LOCAL_DECIDER_URL)
            return {"ok": True, "model": d.get("model"), "device": d.get("device")}
        resp = aws("lambda").invoke(FunctionName=GUARD_FUNCTION, Payload=b'{"health": true}')
        d = json.load(resp["Payload"])
        if d.get("ok"):
            return {"ok": True, "model": d["decider"].get("model"), "device": d["decider"].get("device")}
        return {"ok": False, "error": str(d.get("error", "unhealthy"))[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def host_status():
    if LOCAL:
        return {"state": "local"}
    try:
        inst = aws("ec2").describe_instances(InstanceIds=[GUARD_INSTANCE_ID])["Reservations"][0]["Instances"][0]
        return {"state": inst["State"]["Name"], "type": inst["InstanceType"], "id": GUARD_INSTANCE_ID,
                "schedule": SCHEDULE, "utc_offset": SCHEDULE_UTC_OFFSET, "in_schedule": in_schedule()}
    except Exception as e:
        return {"state": "unknown", "error": str(e)[:200]}


def alarm_summary():
    if LOCAL:
        return {"available": False}
    try:
        alarms = aws("cloudwatch").describe_alarms(AlarmNamePrefix=ALARM_PREFIX)["MetricAlarms"]
        return {"available": True, "configured": len(alarms),
                "in_alarm": [a["AlarmName"][len(ALARM_PREFIX):] for a in alarms if a["StateValue"] == "ALARM"]}
    except Exception as e:
        return {"available": True, "error": str(e)[:200]}


# ---------- overview ----------

def _bins(hours, step):
    end = int(time.time()) // step * step
    return list(range(end - (hours * 3600 // step - 1) * step, end + step, step))


def _epoch(insights_ts):
    import datetime as dt
    return int(dt.datetime.fromisoformat(iso_from_insights(insights_ts).replace("Z", "+00:00")).timestamp())


def overview(hours, policy):
    b, step = bin_for(hours)
    bins = _bins(hours, step)
    out = {"hours": hours, "bin_seconds": step,
           "health": {"guard": guard_health(), "host": host_status(), "alerts": alarm_summary(),
                      "policy": {"updated_at": policy.get("updated_at"), "updated_by": policy.get("updated_by")}}}
    if LOCAL:
        return {**out, **_local_overview(hours, step, bins)}

    res, partial = insights(GUARD_LOG_GROUP, {
        "series": f"filter ispresent(decision) | stats count(*) as n by bin({b}) as t, decision",
        "latency": f"filter ispresent(ms) | stats pct(ms, 50) as p50, pct(ms, 95) as p95 by bin({b}) as t",
        "totals": "filter ispresent(decision) | stats count(*) as n by decision",
        "overall": "filter ispresent(ms) | stats pct(ms, 50) as p50, pct(ms, 95) as p95",
        "by_category": "filter decision != 'allow' | stats count(*) as n by categories | sort n desc | limit 20",
        "by_client": "filter ispresent(decision) | stats count(*) as n by client | sort n desc | limit 10",
        "by_basis": "filter decision != 'allow' and ispresent(basis) | stats count(*) as n by basis | sort n desc",
        "recent": "filter decision != 'allow' | sort @timestamp desc | limit 10 | fields @timestamp, decision, client, sources, categories, ms, basis, evidence",
    }, hours)
    series = {t: {"t": t, "allow": 0, "ask": 0, "block": 0} for t in bins}
    for r in res["series"]:
        t = _epoch(r["t"]) // step * step
        if t in series and r.get("decision") in DECISIONS:
            series[t][r["decision"]] += int(r["n"])
    latency = {t: {"t": t, "p50": None, "p95": None} for t in bins}
    for r in res["latency"]:
        t = _epoch(r["t"]) // step * step
        if t in latency:
            latency[t].update(p50=round(float(r["p50"]), 1), p95=round(float(r["p95"]), 1))
    counts = {r["decision"]: int(r["n"]) for r in res["totals"] if r.get("decision")}
    overall = res["overall"][0] if res["overall"] else {}
    errors = _lambda_metric_series(hours, step, bins)
    return {**out,
            "totals": {"checks": sum(counts.values()), **{d: counts.get(d, 0) for d in DECISIONS},
                       "p50": _f(overall.get("p50")), "p95": _f(overall.get("p95")),
                       "errors": sum(e["errors"] for e in errors), "throttles": sum(e["throttles"] for e in errors)},
            "series": list(series.values()), "latency": list(latency.values()), "errors": errors,
            "by_category": _split_counts(res["by_category"], "categories"),
            "by_client": [{"key": r.get("client") or "-", "n": int(r["n"])} for r in res["by_client"]],
            "by_basis": [{"key": r.get("basis"), "n": int(r["n"])} for r in res["by_basis"] if r.get("basis")],
            "recent": [{"ts": iso_from_insights(r.get("@timestamp")), "decision": r.get("decision"), "client": r.get("client"),
                        "sources": r.get("sources"), "categories": r.get("categories"), "ms": r.get("ms"),
                        "basis": r.get("basis"), "evidence": r.get("evidence")} for r in res["recent"]],
            "partial": partial}


def _count(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _f(v):
    return round(float(v), 1) if v not in (None, "") else None


def _lambda_metric_series(hours, step, bins):
    import datetime as dt
    end = dt.datetime.fromtimestamp(bins[-1] + step, dt.timezone.utc)
    start = dt.datetime.fromtimestamp(bins[0], dt.timezone.utc)
    q = [{"Id": k, "MetricStat": {"Metric": {"Namespace": "AWS/Lambda", "MetricName": m,
                                             "Dimensions": [{"Name": "FunctionName", "Value": GUARD_FUNCTION}]},
                                  "Period": step, "Stat": "Sum"}} for k, m in (("errors", "Errors"), ("throttles", "Throttles"))]
    try:
        data = aws("cloudwatch").get_metric_data(MetricDataQueries=q, StartTime=start, EndTime=end)["MetricDataResults"]
    except Exception:
        data = []
    rows = {t: {"t": t, "errors": 0, "throttles": 0} for t in bins}
    for series in data:
        for ts, v in zip(series["Timestamps"], series["Values"]):
            t = int(ts.timestamp()) // step * step
            if t in rows:
                rows[t][series["Id"]] += int(v)
    return list(rows.values())


def _split_counts(rows, field):
    """'contact,health' rows -> per-category counts."""
    agg = {}
    for r in rows:
        for c in (r.get(field) or "").split(","):
            if c:
                agg[c] = agg.get(c, 0) + int(r.get("n", 0))
    return [{"key": k, "n": n} for k, n in sorted(agg.items(), key=lambda kv: -kv[1])]


def _local_overview(hours, step, bins):
    events = local_events(hours)
    series = {t: {"t": t, "allow": 0, "ask": 0, "block": 0} for t in bins}
    lat = {t: [] for t in bins}
    for e in events:
        t = int(e["_t"]) // step * step
        if t in series and e["decision"] in DECISIONS:
            series[t][e["decision"]] += 1
            if isinstance(e["ms"], (int, float)):
                lat[t].append(e["ms"])
    clients, flagged = {}, [e for e in events if e["decision"] != "allow"]
    for e in events:
        clients[e["client"]] = clients.get(e["client"], 0) + 1
    all_ms = [e["ms"] for e in events if isinstance(e["ms"], (int, float))]
    return {
        "totals": {"checks": len(events), **{d: sum(e["decision"] == d for e in events) for d in DECISIONS},
                   "p50": percentile(all_ms, 50), "p95": percentile(all_ms, 95), "errors": None, "throttles": None},
        "series": list(series.values()),
        "latency": [{"t": t, "p50": percentile(v, 50), "p95": percentile(v, 95)} for t, v in lat.items()],
        "errors": [],
        "by_category": _split_counts([{"categories": e["categories"], "n": 1} for e in flagged], "categories"),
        "by_client": [{"key": k, "n": n} for k, n in sorted(clients.items(), key=lambda kv: -kv[1])],
        "by_basis": [{"key": k, "n": n} for k, n in sorted(_count(e["basis"] for e in flagged if e["basis"]).items(), key=lambda kv: -kv[1])],
        "recent": [{k: e[k] for k in ("ts", "decision", "client", "sources", "categories", "ms", "basis", "evidence")}
                   for e in sorted(flagged, key=lambda e: e["_t"], reverse=True)[:10]],
        "partial": False,
    }


# ---------- decision log ----------

def _clean(value, field):
    value = (value or "").strip()
    if not SAFE.match(value):
        raise ValueError(f"invalid {field} filter")
    return value


def decision_log(params):
    hours = max(1, min(int(params.get("hours", "24")), 24 * 30))
    limit = max(1, min(int(params.get("limit", "200")), 1000))
    decisions = [d for d in _clean(params.get("decision"), "decision").split(",") if d]
    if any(d not in DECISIONS for d in decisions):
        raise ValueError("invalid decision filter")
    client, category, q = (_clean(params.get(k), k) for k in ("client", "category", "q"))
    if LOCAL:
        rows = [e for e in local_events(hours)
                if (not decisions or e["decision"] in decisions) and (not client or e["client"] == client)
                and (not category or category in e["categories"].split(",")) and (not q or q.lower() in e["sources"].lower())]
        rows.sort(key=lambda e: e["_t"], reverse=True)
        return {"rows": [{k: v for k, v in e.items() if k != "_t"} for e in rows[:limit]], "truncated": len(rows) > limit}
    parts = ["fields @timestamp, decision, client, user, user_source, sources, categories, chars, ms, basis, evidence, @requestId", "filter ispresent(decision)"]
    if decisions:
        parts.append("filter decision in [" + ", ".join(f'"{d}"' for d in decisions) + "]")
    if client:
        parts.append(f'filter client = "{client}"')
    if category:
        parts.append(f"filter categories like /{_rx(category)}/")
    if q:
        parts.append(f"filter sources like /(?i){_rx(q)}/ or user like /(?i){_rx(q)}/")   # target or signed-in user
    parts.append(f"sort @timestamp desc | limit {limit + 1}")
    res, partial = insights(GUARD_LOG_GROUP, {"rows": " | ".join(parts)}, hours)
    rows = [{"ts": iso_from_insights(r.get("@timestamp")), "decision": r.get("decision"), "client": r.get("client"), "user": r.get("user") or None, "user_source": r.get("user_source") or None,
             "sources": r.get("sources"), "categories": r.get("categories"), "chars": _int(r.get("chars")),
             "ms": _int(r.get("ms")), "basis": r.get("basis"), "evidence": r.get("evidence"), "request_id": r.get("@requestId")}
            for r in res["rows"]]
    return {"rows": rows[:limit], "truncated": len(rows) > limit, "partial": partial}


def _rx(s):
    return re.escape(s).replace("/", "\\/")


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ---------- admin activity ----------

def admin_activity(hours):
    if LOCAL:
        out, prev = [], None
        try:
            with open(POLICY_FILE + ".history.jsonl") as f:
                for line in f:
                    p = guard_core.normalize_policy(json.loads(line))
                    out.append({"ts": p.get("updated_at"), "by": p.get("updated_by"), "action": "policy_saved",
                                "detail": policy_changes(prev, p)})
                    prev = p
        except FileNotFoundError:
            pass
        return {"rows": out[::-1][:100]}
    res, partial = insights(ADMIN_LOG_GROUP, {
        "rows": "fields @timestamp, @message | filter ispresent(action) | sort @timestamp desc | limit 100"}, hours)
    rows = []
    for r in res["rows"]:
        try:
            m = json.loads(r.get("@message", "{}"))
        except ValueError:
            continue
        rows.append({"ts": iso_from_insights(r.get("@timestamp")), "by": m.get("by"), "action": m.get("action"), "detail": m.get("detail")})
    return {"rows": rows, "partial": partial}
