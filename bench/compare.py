"""Side-by-side: strands-decider guard vs Amazon Bedrock Guardrails on the same samples, plus a cost model.

Inputs (from run.py and guardrails.py): results/pii.jsonl, results/rules_only.jsonl, results/guardrails_*.jsonl,
results/perf_aws.json. Output: COMPARISON.md (no sample text anywhere).

Run:  .venv/bin/python -I compare.py
"""
import json
import math
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
PRICE_PII, PRICE_TOPIC = 0.10 / 1000, 0.15 / 1000          # Seoul list prices per text unit (AWS Pricing API, 2026-10-12)
GPU_HOURLY, EBS_MONTHLY, IPV4_MONTHLY = 0.9896, 9.12, 3.65    # g6.xlarge on-demand Seoul, 100 GB gp3, one public IPv4
PII_SETS = ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth", "dev_public", "dev_synth"]


def load(name):
    with open(os.path.join(RES, name)) as f:
        return [json.loads(l) for l in f]


def prf(rows):
    tp = sum(r["label"] == 1 and r["decision"] == "block" for r in rows)
    fp = sum(r["label"] == 0 and r["decision"] == "block" for r in rows)
    pos = sum(r["label"] == 1 for r in rows)
    neg = sum(r["label"] == 0 for r in rows)
    p = 100 * tp / (tp + fp) if tp + fp else None
    r = 100 * tp / pos if pos else None
    f1 = 2 * p * r / (p + r) if p and r else None
    fpr = 100 * fp / neg if neg else None
    return pos, neg, p, r, f1, fpr


def fmt(v):
    return "-" if v is None else f"{v:.1f}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def main():
    decider = [r for r in load("pii.jsonl") if r["preset"] == "balanced" and r.get("group") != "weak"]
    systems = {"decider (balanced)": decider, "Guardrails PII, all types": load("guardrails_pii_all.jsonl"),
               "Guardrails PII, identifiers only": load("guardrails_pii_ids.jsonl")}
    ids = {r["id"] for r in systems["Guardrails PII, all types"]}
    systems = {k: [r for r in v if r["id"] in ids] for k, v in systems.items()}

    md = ["# strands-decider guard vs Amazon Bedrock Guardrails",
          "",
          "Same samples, same labels (see README.md for the datasets; weak-only positives excluded). "
          "Block = positive. P = precision, R = recall, FPR = false-positive rate on negatives, all in %. "
          "Guardrails configs: **all types** = every identifier entity type plus NAME and ADDRESS, plus the two Korean regexes; "
          "**identifiers only** = without NAME / ADDRESS. Guardrails ran on the DRAFT version, classic tier, input source.",
          ""]

    # ---- per set
    rows = []
    for s in PII_SETS:
        for name, rs in systems.items():
            pos, neg, p, r, f1, fpr = prf([x for x in rs if x["set"] == s])
            rows.append([s, name, pos, neg, fmt(p), fmt(r), fmt(f1), fmt(fpr)])
    md += ["## PII detection per dataset", "", table(["set", "system", "pos", "neg", "P", "R", "F1", "FPR"], rows), ""]

    # ---- pooled by language
    rows = []
    for lang in ("en", "ko"):
        for name, rs in systems.items():
            pos, neg, p, r, f1, fpr = prf([x for x in rs if x["lang"] == lang])
            rows.append([lang, name, pos, neg, fmt(p), fmt(r), fmt(f1), fmt(fpr)])
    md += ["## Pooled by language (all positives vs all negatives, incl. developer negatives)", "",
           table(["lang", "system", "pos", "neg", "P", "R", "F1", "FPR"], rows), ""]

    # ---- developer negatives only
    rows = []
    for name, rs in systems.items():
        dev = [x for x in rs if x["set"] in ("dev_public", "dev_synth")]
        rows.append([name, len(dev), fmt(prf(dev)[5])])
    md += ["## False positives on developer-style text (code, SQL, configs, technical questions)", "",
           table(["system", "samples", "FPR"], rows), ""]

    # ---- per category recall
    cats = sorted({c for x in decider for c in (x.get("cats") or [])})
    rows = []
    for c in cats:
        row = [c]
        for name, rs in systems.items():
            pos = [x for x in rs if x["label"] == 1 and c in (x.get("cats") or [])]
            row.append(f"{fmt(100 * sum(x['decision'] == 'block' for x in pos) / len(pos) if pos else None)} ({len(pos)})")
        rows.append(row)
    md += ["## Recall per information type (positives containing that type)", "", table(["type", *systems], rows), ""]

    # ---- custom rules vs denied topics
    topics = load("guardrails_topics.jsonl")
    topic_ids = {r["id"] for r in topics}
    dec_rules = [r for r in load("rules_only.jsonl") if r["preset"] == "balanced" and r["id"] in topic_ids]
    rows = []
    for rule in sorted({r["rule"] for r in topics}):
        for name, rs in (("decider custom rule (balanced)", dec_rules), ("Guardrails denied topic", topics)):
            pos, neg, p, r, f1, fpr = prf([x for x in rs if x["rule"] == rule])
            rows.append([rule, name, pos, neg, fmt(p), fmt(r), fmt(f1), fmt(fpr)])
    for name, rs in (("decider custom rule (balanced)", dec_rules), ("Guardrails denied topic", topics)):
        pos, neg, p, r, f1, fpr = prf(rs)
        rows.append(["**all**", name, pos, neg, fmt(p), fmt(r), fmt(f1), fmt(fpr)])
    md += ["## Company rules: decider custom rules vs Guardrails denied topics", "",
           "Each rule has positives and hard negatives (a same-named open-source project, negotiation tips, a contract template, "
           "already-published results). A sample counts as blocked if any rule/topic fired.", "",
           table(["rule", "system", "pos", "neg", "P", "R", "F1", "FPR"], rows), ""]

    # ---- latency
    def pct(v, q):
        v = sorted(v)
        return v[min(len(v) - 1, int(round(q / 100 * (len(v) - 1))))] if v else None
    g_ms = [x["ms"] for x in systems["Guardrails PII, all types"]]
    perf = {}
    try:
        with open(os.path.join(RES, "perf_aws.json")) as f:
            perf = json.load(f)
    except FileNotFoundError:
        pass
    seq = (perf.get("sequential") or {}).get("client_round_trip_ms") or {}
    md += ["## Latency (client round trip from Seoul-region caller, ms)", "",
           table(["system", "p50", "p95", "p99", "note"], [
               ["Guardrails ApplyGuardrail (PII)", pct(g_ms, 50), pct(g_ms, 95), pct(g_ms, 99), f"{len(g_ms)} calls, 4 in parallel"],
               ["decider guard Lambda", seq.get("p50", "see RESULTS.md"), seq.get("p95", ""), seq.get("p99", ""), "sequential, from perf.py"]]), ""]

    # ---- cost
    n = len(systems["Guardrails PII, all types"])
    units = sum(x["units_pii"] for x in systems["Guardrails PII, all types"])
    avg_chars = sum(x["len"] for x in systems["Guardrails PII, all types"]) / n
    t_units = sum(x["units_topics"] for x in topics)
    md += ["## Cost", "",
           f"Measured on this run: {n} PII checks used **{units} paid text units** ({units / n:.2f} per check, average {avg_chars:.0f} characters); "
           f"{len(topics)} topic checks used {t_units} units. This benchmark cost about "
           f"${2 * units * PRICE_PII + t_units * PRICE_TOPIC:.2f} on Guardrails (two PII configs + topics).", "",
           "Guardrails is billed per text unit (up to 1,000 characters), so long inputs such as file contents cost more. "
           "The decider guard is billed per GPU hour regardless of volume; one g6.xlarge sustained about 4 checks/s in perf.py.", ""]
    gpu_biz = 8 * 22 * GPU_HOURLY + EBS_MONTHLY + IPV4_MONTHLY
    gpu_247 = 730 * GPU_HOURLY + EBS_MONTHLY + IPV4_MONTHLY
    capacity = 3.5                     # sustained checks/s per g6.xlarge host (perf.py measured ~3.9 with 4 workers)
    rows = []
    for devs, per_day, chars in ((10, 200, 1500), (50, 300, 2000), (200, 300, 2000), (500, 400, 3000)):
        checks = devs * per_day * 22
        u = checks * math.ceil(chars / 1000)
        g_pii = u * PRICE_PII
        g_all = u * (PRICE_PII + PRICE_TOPIC)
        load_avg = checks / (8 * 22 * 3600)
        hosts = max(1, math.ceil(load_avg * 3 / capacity))   # peak ~3x the business-hours average
        rows.append([f"{devs} devs × {per_day} checks/day × 22 days, {chars} chars avg", f"{checks:,}", f"{u:,}",
                     f"${g_pii:,.0f}", f"${g_all:,.0f}", f"${gpu_biz * hosts:,.0f}", f"${gpu_247 * hosts:,.0f}",
                     f"{load_avg:.2f} → {hosts} host{'s' if hosts > 1 else ''}"])
    md += [table(["scenario", "checks/month", "text units", "Guardrails PII only", "Guardrails PII + topics",
                  "decider, hosts on 8h × 22d", "decider, hosts 24/7", "avg checks/s → GPU hosts (peak 3× avg)"], rows), "",
           f"Break-even (PII + topics, {2} text units per check): about "
           f"{gpu_biz / ((PRICE_PII + PRICE_TOPIC) * 2):,.0f} checks/month for a business-hours host, "
           f"{gpu_247 / ((PRICE_PII + PRICE_TOPIC) * 2):,.0f} for a 24/7 host. "
           "Lambda, S3, CloudWatch and the console add cents at these volumes. Prices: Seoul on-demand list prices; "
           "Savings Plans / Spot lower the GPU side, and Guardrails has no idle cost.", ""]
    with open(os.path.join(HERE, "COMPARISON.md"), "w") as f:
        f.write("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
