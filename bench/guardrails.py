"""Amazon Bedrock Guardrails on the same evaluation sets, for a side-by-side comparison with the decider.

Three guardrails are created for the run (and deleted afterwards unless --keep):
  pii_all      sensitive-information filter, all identifier entity types incl. NAME and ADDRESS, plus two regexes
               (Korean resident number and mobile number, as the decider's regexes do), action BLOCK
  pii_ids      the same without NAME / ADDRESS (fewer false alarms on code and prose that mentions people)
  topics       denied topics written from the 4 custom rules (rules.py), the Guardrails counterpart of custom rules

Per-sample results (ids, labels, decision, entity types, text units, latency - never text) go to
results/guardrails_<config>.jsonl; cost uses the Seoul list prices read from the AWS Pricing API on 2026-10-12:
sensitive information (PII entities) $0.10 / 1,000 text units, regexes free, denied topics $0.15 / 1,000 text units
(a text unit is up to 1,000 characters).

Run:  .venv/bin/python -I guardrails.py [--region ap-northeast-2] [--workers 4] [--keep]
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rules import RULES  # noqa: E402

SETS = os.path.join(HERE, "data", "sets")
RES = os.path.join(HERE, "results")
PII_SETS = ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth", "dev_public", "dev_synth"]
PRICE = {"pii": 0.10 / 1000, "topics": 0.15 / 1000}

ENTITIES_IDS = ["AWS_ACCESS_KEY", "AWS_SECRET_KEY", "CREDIT_DEBIT_CARD_NUMBER", "CREDIT_DEBIT_CARD_CVV", "CREDIT_DEBIT_CARD_EXPIRY",
                "DRIVER_ID", "EMAIL", "INTERNATIONAL_BANK_ACCOUNT_NUMBER", "PASSWORD", "PHONE", "PIN", "SWIFT_CODE",
                "US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER",
                "US_SOCIAL_SECURITY_NUMBER", "CA_HEALTH_NUMBER", "CA_SOCIAL_INSURANCE_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER",
                "UK_NATIONAL_INSURANCE_NUMBER", "UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER", "VEHICLE_IDENTIFICATION_NUMBER"]
ENTITIES_ALL = ENTITIES_IDS + ["NAME", "ADDRESS"]
REGEXES = [  # same shapes as guard_core's Korean patterns
    {"name": "kr_resident_id", "pattern": r"\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\s?-\s?[1-8]\d{6}", "action": "BLOCK"},
    {"name": "kr_mobile", "pattern": r"01[016789][ .-]?\d{3,4}[ .-]?\d{4}", "action": "BLOCK"},
]
TOPIC_DEFS = {  # the 4 custom rules, rewritten as denied-topic definitions (max 200 chars)
    "kestrel": ("Project Kestrel unreleased", "Unreleased plans, schedules, budgets, features or partners of the company's internal project code-named Kestrel."),
    "comp": ("Employee compensation", "A specific employee's compensation (salary, bonus, equity) or the result of their performance review."),
    "contract": ("Customer contract terms", "The amount, pricing, discount or specific terms of a contract with a named customer."),
    "fin": ("Unpublished financials", "Company financial results or forecasts (revenue, profit, guidance) that have not yet been publicly released."),
}
assert set(TOPIC_DEFS) == {r["id"] for r in RULES}


def bedrock(region):
    return boto3.client("bedrock", region_name=region)


def runtime(region):
    return boto3.client("bedrock-runtime", region_name=region, config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))


def create(region, name, **policy):
    b = bedrock(region)
    for g in b.list_guardrails().get("guardrails", []):
        if g["name"] == name:
            b.delete_guardrail(guardrailIdentifier=g["id"])
            time.sleep(2)
    gid = b.create_guardrail(name=name, description="decider-guard benchmark (temporary)",
                             blockedInputMessaging="blocked", blockedOutputsMessaging="blocked", **policy)["guardrailId"]
    for _ in range(60):
        if b.get_guardrail(guardrailIdentifier=gid, guardrailVersion="DRAFT")["status"] == "READY":
            return gid
        time.sleep(2)
    raise RuntimeError(f"guardrail {name} not ready")


def apply(rt, gid, rec):
    t0 = time.time()
    for attempt in range(8):
        try:
            r = rt.apply_guardrail(guardrailIdentifier=gid, guardrailVersion="DRAFT", source="INPUT",
                                   content=[{"text": {"text": rec["text"][:25000]}}])
            break
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("ThrottlingException", "ServiceUnavailableException") or attempt == 7:
                raise
            time.sleep(1 + attempt + random.random())
    a = (r.get("assessments") or [{}])[0]
    types = sorted({e["type"] for e in a.get("sensitiveInformationPolicy", {}).get("piiEntities", [])} |
                   {x["name"] for x in a.get("sensitiveInformationPolicy", {}).get("regexes", [])} |
                   {t["name"] for t in a.get("topicPolicy", {}).get("topics", [])})
    u = r.get("usage", {})
    return {k: rec.get(k) for k in ("id", "set", "lang", "label", "cats", "group", "rule")} | {
        "decision": "block" if r["action"] == "GUARDRAIL_INTERVENED" else "allow", "types": types,
        "units_pii": u.get("sensitiveInformationPolicyUnits", 0), "units_free": u.get("sensitiveInformationPolicyFreeUnits", 0),
        "units_topics": u.get("topicPolicyUnits", 0), "ms": round((time.time() - t0) * 1000), "len": len(rec["text"])}


def load(name):
    with open(os.path.join(SETS, f"{name}.jsonl")) as f:
        return [json.loads(l) for l in f]


def run(region, gid, recs, out, workers):
    rt = runtime(region)
    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(lambda r: apply(rt, gid, r), recs))
    with open(os.path.join(RES, out), "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    blocked = sum(r["decision"] == "block" for r in rows)
    units = sum(r["units_pii"] + r["units_topics"] for r in rows)
    print(f"  {out}: {len(rows)} samples, {blocked} blocked, {units} paid text units")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="ap-northeast-2")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep", action="store_true", help="keep the guardrails after the run")
    args = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    pii = [r for s in PII_SETS for r in load(s) if r.get("group") != "weak"]
    rules = load("rules")
    print(f"samples: {len(pii)} PII-set, {len(rules)} rule-set")

    configs = {
        "pii_all": {"sensitiveInformationPolicyConfig": {"piiEntitiesConfig": [{"type": t, "action": "BLOCK"} for t in ENTITIES_ALL],
                                                         "regexesConfig": REGEXES}},
        "pii_ids": {"sensitiveInformationPolicyConfig": {"piiEntitiesConfig": [{"type": t, "action": "BLOCK"} for t in ENTITIES_IDS],
                                                         "regexesConfig": REGEXES}},
        "topics": {"topicPolicyConfig": {"topicsConfig": [{"name": n, "definition": d, "type": "DENY"} for n, d in TOPIC_DEFS.values()]}},
    }
    created = {}
    try:
        for name, policy in configs.items():
            created[name] = create(args.region, f"decider-bench-{name.replace('_', '-')}", **policy)
            print(f"guardrail {name}: {created[name]}")
            run(args.region, created[name], rules if name == "topics" else pii, f"guardrails_{name}.jsonl", args.workers)
    finally:
        if not args.keep:
            for gid in created.values():
                bedrock(args.region).delete_guardrail(guardrailIdentifier=gid)
            print("deleted the benchmark guardrails")


if __name__ == "__main__":
    main()
