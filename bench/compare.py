"""Side-by-side: strands-decider guard vs Amazon Bedrock Guardrails on the same samples, plus a cost model.

Inputs (from run.py and guardrails.py): results/pii.jsonl, results/rules_only.jsonl, results/guardrails_*.jsonl,
results/perf_aws.json. Output: COMPARISON.md (no sample text anywhere).

Run:  .venv/bin/python -I compare.py
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
PRICE_PII, PRICE_TOPIC = 0.10 / 1000, 0.15 / 1000          # Seoul list prices per text unit (AWS Pricing API, 2026-10-12)
GPU_HOURLY, EBS_MONTHLY, IPV4_MONTHLY = 0.9896, 9.12, 3.65    # g6.xlarge on-demand Seoul, 100 GB gp3, one public IPv4
PII_SETS = ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth", "private_life", "dev_public", "dev_synth"]


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
    sys.path.insert(0, HERE)
    from features import split_of
    rows_all = [r for r in load("pii.jsonl") if r.get("group") != "weak"]
    decider = [r for r in rows_all if r["preset"] == "balanced"]
    systems = {"decider (balanced)": decider, "decider (strict)": [r for r in rows_all if r["preset"] == "strict"],
               "Guardrails PII, all types": load("guardrails_pii_all.jsonl"),
               "Guardrails PII, identifiers only": load("guardrails_pii_ids.jsonl")}
    # Holdout half only: the decider's thresholds were tuned on the other half (tune.py), Guardrails was not tuned at all.
    ids = {r["id"] for r in systems["Guardrails PII, all types"] if split_of(r["id"]) == "holdout"}
    systems = {k: [r for r in v if r["id"] in ids] for k, v in systems.items()}

    md = ["# strands-decider guard vs Amazon Bedrock Guardrails",
          "",
          "Same samples, same labels (see README.md for the datasets; weak-only positives excluded). PII tables use the **holdout half** "
          "only: the decider's thresholds were tuned on the other half (see TUNING.md); Guardrails was not tuned. "
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
    # Host options, Seoul prices (Pricing API / Spot price history, 2026-10-12). Throughput from perf.py and probe_instances.py.
    HOURS_SCHED = 12 * 21.7                       # weekdays 08:00-20:00
    options = [  # name, $/h, hours/month, checks/s per host, note
        ("g6.xlarge on-demand, 24/7", 0.9896, 730, 3.5, "current default"),
        ("g6.xlarge on-demand, weekdays 08-20", 0.9896, HOURS_SCHED, 3.5, "--schedule; regex-only outside the window"),
        ("g6.xlarge 1-yr reserved (no upfront), 24/7", 0.6442, 730, 3.5, "commitment; billed even when stopped"),
        ("g6.xlarge Spot, 24/7", 0.47, 730, 3.5, "--spot; interruptions fall back to regex-only"),
        ("g6.xlarge Spot, weekdays 08-20", 0.47, HOURS_SCHED, 3.5, "--spot --schedule"),
        ("g4dn.xlarge (T4) on-demand, weekdays 08-20", 0.647, HOURS_SCHED, 1.0, "~3x slower: 0.8-1.0 s per check"),
    ]
    def host_cost(rate, hours):
        return rate * hours + EBS_MONTHLY + IPV4_MONTHLY * hours / 730   # the auto-assigned public IP is released while stopped
    md += ["### GPU host options", "",
           "Measured on probe instances: g4dn.xlarge (T4) 0.78 s per short check and ~1 check/s; g6f fractional-GPU types ran on CPU "
           "with the GPU image (they need NVIDIA GRID drivers) at ~7 s per check, which also rules out CPU-only instances for interactive hooks.", "",
           table(["option", "$/month (1 host)", "checks/s per host", "note"],
                 [[n, f"${host_cost(r, h):,.0f}", c, note] for n, r, h, c, note in options]), ""]
    rows = []
    for devs, per_day, chars in ((10, 200, 1500), (50, 300, 2000), (200, 300, 2000), (500, 400, 3000)):
        checks = devs * per_day * 22
        u = checks * math.ceil(chars / 1000)
        load_avg = checks / (HOURS_SCHED * 3600)
        row = [f"{devs} devs × {per_day}/day, {chars} chars", f"{checks:,}", f"${u * PRICE_PII:,.0f}", f"${u * (PRICE_PII + PRICE_TOPIC):,.0f}"]
        for n, r, h, c, note in (options[0], options[1], options[4], options[5]):
            hosts = max(1, math.ceil(load_avg * 3 / c))   # peak ~3x the average
            row.append(f"${host_cost(r, h) * hosts:,.0f} ({hosts})")
        rows.append(row)
    md += ["### Monthly cost by team size (number of GPU hosts in brackets)", "",
           table(["scenario", "checks/month", "Guardrails PII", "Guardrails PII + topics", "decider 24/7", "decider weekdays 08-20",
                  "decider Spot weekdays 08-20", "decider g4dn weekdays 08-20"], rows), "",
           "Guardrails has no idle cost and is cheapest for small teams; the decider's cost is flat per host, so it wins as volume or "
           "text length grows, and the schedule + Spot options cut it by about 80 % against on-demand 24/7. Lambda, S3, CloudWatch and "
           "the console add cents at these volumes.", ""]
    with open(os.path.join(HERE, "COMPARISON.md"), "w") as f:
        f.write("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
