"""Alerts: email recipients (SNS) and CloudWatch alarms the console can switch on and tune.

The alarms are created and updated by this Lambda (not by CloudFormation) so admins can change
thresholds without a redeploy; destroy.sh deletes them by prefix. The settings live in the policy
bucket as alerts.json. A 5-minute EventBridge schedule calls health_check(), which publishes the
GuardHealthy metric that the "guard down" alarm watches.
"""
import json
import re

from common import (ALARM_PREFIX, ALERTS_KEY, ALERTS_TOPIC, GUARD_FUNCTION, LOCAL, METRIC_NAMESPACE, POLICY_BUCKET, aws, in_schedule)
from monitoring import guard_health

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAILS = 20

# rule id -> (default settings, alarm definition builder)
DEFAULTS = {
    "guard_down": {"enabled": True},
    "guard_errors": {"enabled": True},
    "block_spike": {"enabled": False, "threshold": 20},
    "latency": {"enabled": False, "threshold_ms": 3000},
}


def _alarm(rule, cfg):
    lam = [{"Name": "FunctionName", "Value": GUARD_FUNCTION}]
    base = {"AlarmName": ALARM_PREFIX + rule, "AlarmActions": [ALERTS_TOPIC], "OKActions": [ALERTS_TOPIC], "Period": 300}
    if rule == "guard_down":
        return {**base, "AlarmDescription": "The guard health check failed (model host down or unreachable).",
                "Namespace": METRIC_NAMESPACE, "MetricName": "GuardHealthy", "Statistic": "Minimum",
                "EvaluationPeriods": 2, "Threshold": 1, "ComparisonOperator": "LessThanThreshold",
                "TreatMissingData": "notBreaching"}  # no data = outside the host schedule
    if rule == "guard_errors":
        return {**base, "AlarmDescription": "The guard Lambda returned errors.", "Namespace": "AWS/Lambda", "MetricName": "Errors",
                "Dimensions": lam, "Statistic": "Sum", "EvaluationPeriods": 1, "Threshold": 0,
                "ComparisonOperator": "GreaterThanThreshold", "TreatMissingData": "notBreaching"}
    if rule == "block_spike":
        return {**base, "AlarmDescription": f"More than {cfg['threshold']} blocks in 5 minutes.", "Namespace": METRIC_NAMESPACE,
                "MetricName": "Blocks", "Statistic": "Sum", "EvaluationPeriods": 1, "Threshold": cfg["threshold"],
                "ComparisonOperator": "GreaterThanThreshold", "TreatMissingData": "notBreaching"}
    if rule == "latency":
        return {**base, "AlarmDescription": f"Guard p95 latency above {cfg['threshold_ms']} ms for 10 minutes.", "Namespace": "AWS/Lambda",
                "MetricName": "Duration", "Dimensions": lam, "ExtendedStatistic": "p95", "EvaluationPeriods": 2,
                "Threshold": cfg["threshold_ms"], "ComparisonOperator": "GreaterThanThreshold", "TreatMissingData": "notBreaching"}
    raise ValueError(rule)


def normalize(cfg):
    cfg = cfg or {}
    out = {"emails": [], "rules": {k: dict(v) for k, v in DEFAULTS.items()}}
    emails = [str(e).strip() for e in cfg.get("emails", []) if str(e).strip()]
    if len(emails) > MAX_EMAILS or any(not EMAIL.match(e) for e in emails):
        raise ValueError("invalid email list")
    out["emails"] = sorted(set(emails))
    for rule, values in (cfg.get("rules") or {}).items():
        if rule not in DEFAULTS:
            raise ValueError(f"unknown alert rule: {rule}")
        r = out["rules"][rule]
        r["enabled"] = bool(values.get("enabled", r["enabled"]))
        if "threshold" in r:
            r["threshold"] = max(1, min(int(values.get("threshold", r["threshold"])), 100000))
        if "threshold_ms" in r:
            r["threshold_ms"] = max(100, min(int(values.get("threshold_ms", r["threshold_ms"])), 60000))
    return out


def load():
    if LOCAL:
        return None
    s3 = aws("s3")
    try:
        return normalize(json.load(s3.get_object(Bucket=POLICY_BUCKET, Key=ALERTS_KEY)["Body"]))
    except s3.exceptions.NoSuchKey:
        return normalize(None)


def status():
    """Settings + subscription states + alarm states, for the Alerts tab."""
    if LOCAL:
        return {"available": False}
    cfg = load()
    subs = aws("sns").list_subscriptions_by_topic(TopicArn=ALERTS_TOPIC).get("Subscriptions", [])
    by_email = {s["Endpoint"]: ("pending" if s["SubscriptionArn"] == "PendingConfirmation" else "confirmed")
                for s in subs if s["Protocol"] == "email"}
    alarms = {a["AlarmName"][len(ALARM_PREFIX):]: a for a in aws("cloudwatch").describe_alarms(AlarmNamePrefix=ALARM_PREFIX)["MetricAlarms"]}
    return {
        "available": True,
        "emails": [{"email": e, "status": by_email.get(e, "missing")} for e in cfg["emails"]],
        "rules": {k: {**v, "state": alarms[k]["StateValue"] if k in alarms else None,
                      "since": alarms[k]["StateUpdatedTimestamp"].isoformat() if k in alarms else None}
                  for k, v in cfg["rules"].items()},
    }


def save(cfg):
    """Store settings and make SNS + CloudWatch match them. Returns the list of applied changes."""
    if LOCAL:
        raise ValueError("alerts need the AWS deployment")
    cfg = normalize(cfg)
    old = load()
    aws("s3").put_object(Bucket=POLICY_BUCKET, Key=ALERTS_KEY, Body=json.dumps(cfg, indent=2).encode(), ContentType="application/json")
    changes = []
    sns, cw = aws("sns"), aws("cloudwatch")
    subs = sns.list_subscriptions_by_topic(TopicArn=ALERTS_TOPIC).get("Subscriptions", [])
    existing = {s["Endpoint"]: s["SubscriptionArn"] for s in subs if s["Protocol"] == "email"}
    for e in cfg["emails"]:
        if e not in existing:
            sns.subscribe(TopicArn=ALERTS_TOPIC, Protocol="email", Endpoint=e)
            changes.append({"kind": "email_added", "value": e})
    for e, arn in existing.items():
        if e not in cfg["emails"]:
            if arn.startswith("arn:"):  # pending subscriptions cannot be removed; they expire after 3 days
                sns.unsubscribe(SubscriptionArn=arn)
            changes.append({"kind": "email_removed", "value": e})
    for rule, r in cfg["rules"].items():
        if r["enabled"]:
            cw.put_metric_alarm(**_alarm(rule, r))
        else:
            cw.delete_alarms(AlarmNames=[ALARM_PREFIX + rule])
        if old["rules"][rule] != r:
            changes.append({"kind": "rule", "id": rule, **r})
    return cfg, changes


def send_test(user):
    if LOCAL:
        raise ValueError("alerts need the AWS deployment")
    aws("sns").publish(TopicArn=ALERTS_TOPIC, Subject="[DeciderGuard] test notification",
                       Message=f"This is a test notification sent from the policy console by {user}.\n"
                               "If you received it, alert emails reach you.")


def health_check():
    """Scheduled every 5 minutes: publish GuardHealthy = 1 / 0 (nothing while the schedule has the host off)."""
    if not in_schedule():
        print(json.dumps({"health_check": "skipped", "reason": "outside schedule"}))
        return {"skipped": True}
    h = guard_health()
    aws("cloudwatch").put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=[
        {"MetricName": "GuardHealthy", "Value": 1 if h.get("ok") else 0, "Unit": "Count"}])
    print(json.dumps({"health_check": "ok" if h.get("ok") else "failed", "detail": h}))
    return h
