"""Compute metrics from results/*.jsonl and write results/metrics.json + RESULTS.md (tables only, no text).

The hand-written "## Findings" section of an existing RESULTS.md is preserved.
Run:  .venv/bin/python -I report.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
SETS = os.path.join(HERE, "data", "sets")
sys.path.insert(0, HERE)
from rules import RULES  # noqa: E402

PRESETS = ("lenient", "balanced", "strict")
CATS = ["resident_id", "gov_id", "financial", "contact", "health", "credential"]
SET_ORDER = ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth"]


def load(name):
    p = os.path.join(RES, name + ".jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f]


def prf(pos, neg, hit):
    tp = sum(1 for r in pos if hit(r))
    fp = sum(1 for r in neg if hit(r))
    rec = tp / len(pos) if pos else None
    prec = tp / (tp + fp) if neg and (tp + fp) else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    fpr = fp / len(neg) if neg else None
    return {"tp": tp, "fp": fp, "n_pos": len(pos), "n_neg": len(neg), "precision": prec, "recall": rec, "f1": f1, "fpr": fpr}


BLOCK = lambda r: r["decision"] == "block"  # noqa: E731
FLAG = lambda r: r["decision"] in ("block", "ask")  # noqa: E731


def f(x, pct=True):
    if x is None:
        return "-"
    return f"{100 * x:.1f}" if pct else f"{x:.3f}"


def is_pos(r):
    return r["label"] == 1 and (r["group"] in ("strong", "value", "context"))


def pii_metrics(rows):
    M = {"per_set": {}, "pooled": {}, "per_category": {}, "attribution": {}, "weak": {}, "ko_kind": {}, "dev_neg": {}}
    for p in PRESETS:
        R = [r for r in rows if r["preset"] == p]
        for s in SET_ORDER:
            pos = [r for r in R if r["set"] == s and is_pos(r)]
            neg = [r for r in R if r["set"] == s and r["label"] == 0]
            M["per_set"][f"{s}|{p}"] = {"block": prf(pos, neg, BLOCK), "flag": prf(pos, neg, FLAG)}
            weak = [r for r in R if r["set"] == s and r["group"] == "weak"]
            if weak:
                M["weak"][f"{s}|{p}"] = {"n": len(weak), "block": sum(map(BLOCK, weak)) / len(weak),
                                         "flag": sum(map(FLAG, weak)) / len(weak)}
        dev = [r for r in R if r["set"] in ("dev_public", "dev_synth")]
        for lang in ("en", "ko"):
            pos = [r for r in R if r["set"] in SET_ORDER and r["lang"] == lang and is_pos(r)]
            neg = [r for r in R if r["label"] == 0 and r["lang"] == lang]
            M["pooled"][f"{lang}|{p}"] = {"block": prf(pos, neg, BLOCK), "flag": prf(pos, neg, FLAG)}
        groups = {}
        for r in dev:
            sub = r["id"].split("-")[1].rstrip("0123456789") or "x"
            key = f"{r['set']}:{sub if r['set'] == 'dev_public' else r['lang']}"
            groups.setdefault(key, []).append(r)
        M["dev_neg"][p] = {k: {"n": len(v), "block": sum(map(BLOCK, v)) / len(v), "flag": sum(map(FLAG, v)) / len(v)}
                           for k, v in sorted(groups.items())}
        allpos = [r for r in R if r["set"] in SET_ORDER and is_pos(r)]
        for c in CATS:
            xs = [r for r in allpos if c in r["cats"]]
            if xs:
                M["per_category"][f"{c}|{p}"] = {"n": len(xs), "block": sum(map(BLOCK, xs)) / len(xs),
                                                 "flag": sum(map(FLAG, xs)) / len(xs)}
        for s in SET_ORDER + ["all"]:
            xs = [r for r in R if r["decision"] == "block" and (s == "all" or r["set"] == s)]
            cnt = {}
            for r in xs:
                cnt[r["by"]] = cnt.get(r["by"], 0) + 1
            M["attribution"][f"{s}|{p}"] = {"blocks": len(xs), **{k: v / len(xs) for k, v in cnt.items()}} if xs else {"blocks": 0}
        ko = [r for r in R if r["set"] == "ko_synth" and r["label"] == 1]
        for k in sorted({r["kind"] for r in ko}):
            xs = [r for r in ko if r["kind"] == k]
            M["ko_kind"][f"{k}|{p}"] = {"n": len(xs), "block": sum(map(BLOCK, xs)) / len(xs), "flag": sum(map(FLAG, xs)) / len(xs)}
    return M


def fired(r, rid):
    return any(f["source"] == "rule" and f["type"] == rid for f in r["findings"])


def rule_metrics(rows):
    M = {}
    for p in PRESETS:
        R = [r for r in rows if r["preset"] == p]
        for rule in RULES:
            rid = rule["id"]
            pos = [r for r in R if r.get("rule") == rid and r["label"] == 1]
            others = [r for r in R if not (r.get("rule") == rid and r["label"] == 1)]
            hard = [r for r in R if r.get("rule") == rid and r["label"] == 0]
            dev = [r for r in R if r["set"] in ("dev_public", "dev_synth")]
            m = prf(pos, others, lambda r: fired(r, rid))
            m["hard_neg_fpr"] = sum(1 for r in hard if fired(r, rid)) / len(hard) if hard else None
            m["dev_fpr"] = sum(1 for r in dev if fired(r, rid)) / len(dev) if dev else None
            for lang in ("en", "ko"):
                lp = [r for r in pos if r["lang"] == lang]
                lh = [r for r in hard if r["lang"] == lang]
                m[f"recall_{lang}"] = sum(1 for r in lp if fired(r, rid)) / len(lp) if lp else None
                m[f"hard_fpr_{lang}"] = sum(1 for r in lh if fired(r, rid)) / len(lh) if lh else None
            M[f"{rid}|{p}"] = m
        rs = [r for r in R if r["set"] == "rules"]
        dec_pos = [r for r in rs if r["label"] == 1]
        dec_neg = [r for r in rs if r["label"] == 0]
        M[f"decision|{p}"] = {"block": prf(dec_pos, dec_neg, BLOCK), "flag": prf(dec_pos, dec_neg, FLAG),
                              "neg_blocked_by_pii": sum(1 for r in dec_neg if r["decision"] == "block" and r["by"] in ("model", "regex", "regex+model", "model+rule")) / max(1, len(dec_neg))}
        dev = [r for r in R if r["set"] in ("dev_public", "dev_synth")]
        if dev:
            M[f"dev_any_rule|{p}"] = sum(1 for r in dev if r["decision"] != "allow") / len(dev)
    return M


def counts():
    out = {}
    for fn in sorted(os.listdir(SETS)):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(SETS, fn)) as fh:
            rows = [json.loads(l) for l in fh]
        c = {}
        for r in rows:
            k = "neg" if r["label"] == 0 else ("pos" if r["group"] in ("strong", "value", "context", "pos") else r["group"])
            c[k] = c.get(k, 0) + 1
        out[fn[:-6]] = c
    return out


def md_table(head, rows):
    s = "| " + " | ".join(head) + " |\n|" + "|".join("---" for _ in head) + "|\n"
    return s + "".join("| " + " | ".join(str(x) for x in r) + " |\n" for r in rows)


def render(M, cnt, perf_l, perf_a, health):
    o = []
    o.append("# Benchmark results\n")
    o.append(f"Generated {time.strftime('%Y-%m-%d %H:%M %Z')} by `report.py`. Model `{health.get('model', '?')}` on "
             f"`{health.get('device', '?')}` (local strands-decider). Percentages; P = precision, R = recall, "
             "FPR = false-positive rate on negatives. \"block\" = only block counts as positive; "
             "\"block/ask\" = block or ask counts as positive. No sample text appears in this file.\n")
    o.append("## Sample counts\n")
    o.append(md_table(["set", "positives", "weak-only (names/dates)", "negatives"],
                      [[k, v.get("pos", 0), v.get("weak", 0), v.get("neg", 0)] for k, v in cnt.items()]))
    pm = M.get("pii")
    if pm:
        o.append("\n## PII detection per dataset and preset\n")
        o.append("Datasets without negatives have no precision/FPR on their own (see pooled table).\n")
        rows = []
        for s in SET_ORDER:
            for p in PRESETS:
                b, fl = pm["per_set"][f"{s}|{p}"]["block"], pm["per_set"][f"{s}|{p}"]["flag"]
                rows.append([s, p, b["n_pos"], b["n_neg"], f(b["precision"]), f(b["recall"]), f(b["f1"]), f(b["fpr"]),
                             f(fl["precision"]), f(fl["recall"]), f(fl["f1"]), f(fl["fpr"])])
        o.append(md_table(["set", "preset", "pos", "neg", "P block", "R block", "F1 block", "FPR block",
                           "P block/ask", "R block/ask", "F1 block/ask", "FPR block/ask"], rows))
        o.append("\n### Pooled by language (all positives vs all negatives incl. developer negatives)\n")
        rows = []
        for lang in ("en", "ko"):
            for p in PRESETS:
                b, fl = pm["pooled"][f"{lang}|{p}"]["block"], pm["pooled"][f"{lang}|{p}"]["flag"]
                rows.append([lang, p, b["n_pos"], b["n_neg"], f(b["precision"]), f(b["recall"]), f(b["f1"]), f(b["fpr"]),
                             f(fl["precision"]), f(fl["recall"]), f(fl["f1"]), f(fl["fpr"])])
        o.append(md_table(["lang", "preset", "pos", "neg", "P block", "R block", "F1 block", "FPR block",
                           "P block/ask", "R block/ask", "F1 block/ask", "FPR block/ask"], rows))
        o.append("\n### Recall per guard category (all PII datasets, block / block-or-ask)\n")
        rows = []
        for c in CATS:
            r = [c, pm["per_category"].get(f"{c}|balanced", {}).get("n", 0)]
            for p in PRESETS:
                x = pm["per_category"].get(f"{c}|{p}")
                r.append(f"{f(x['block'])} / {f(x['flag'])}" if x else "-")
            rows.append(r)
        o.append(md_table(["category", "n", "lenient", "balanced", "strict"], rows))
        o.append("\n### Korean synthetic set: recall per kind (block / block-or-ask)\n")
        kinds = sorted({k.split("|")[0] for k in pm["ko_kind"]})
        rows = [[k, pm["ko_kind"][f"{k}|balanced"]["n"]] + [f"{f(pm['ko_kind'][f'{k}|{p}']['block'])} / {f(pm['ko_kind'][f'{k}|{p}']['flag'])}" for p in PRESETS] for k in kinds]
        o.append(md_table(["kind", "n", "lenient", "balanced", "strict"], rows))
        o.append("\n### Weak-only samples (only names, dates, companies, cities, URLs): share blocked / flagged\n")
        rows = [[s] + [f"{f(pm['weak'][f'{s}|{p}']['block'])} / {f(pm['weak'][f'{s}|{p}']['flag'])}" for p in PRESETS]
                for s in SET_ORDER if f"{s}|balanced" in pm["weak"]]
        o.append(md_table(["set", "lenient", "balanced", "strict"], rows))
        o.append("\n### Developer-style negatives: false-positive rate (block / block-or-ask)\n")
        keys = list(pm["dev_neg"]["balanced"])
        rows = [[k, pm["dev_neg"]["balanced"][k]["n"]] + [f"{f(pm['dev_neg'][p][k]['block'])} / {f(pm['dev_neg'][p][k]['flag'])}" for p in PRESETS] for k in keys]
        o.append(md_table(["subset", "n", "lenient", "balanced", "strict"], rows))
        o.append("\n### Who produced the block (share of all blocks)\n")
        o.append("regex = strong pattern (resident number, card, keys), model not consulted; regex+model = weak pattern "
                 "(email/phone/...) confirmed by the model; model = model only.\n")
        rows = []
        for s in SET_ORDER + ["all"]:
            for p in PRESETS:
                a = pm["attribution"][f"{s}|{p}"]
                rows.append([s, p, a["blocks"], f(a.get("regex", 0)), f(a.get("regex+model", 0)), f(a.get("model", 0))])
        o.append(md_table(["set", "preset", "blocks", "regex", "regex+model", "model"], rows))
    for key, title in (("rules_only", "Custom rules only (all PII categories = allow)"),
                       ("rules_default", "Custom rules + default PII categories")):
        rm = M.get(key)
        if not rm:
            continue
        o.append(f"\n## {title}\n")
        o.append("Rule sensitivity = global preset in each column. P/R per rule: a rule \"fires\" when its own finding is "
                 "raised; precision counts firings on every other sample (other rules' samples, hard negatives"
                 + (", developer negatives" if key == "rules_only" else "") + ").\n")
        rows = []
        for rule in RULES:
            for p in PRESETS:
                m = rm[f"{rule['id']}|{p}"]
                rows.append([rule["name"], p, m["n_pos"], f(m["precision"]), f(m["recall"]), f(m["f1"]),
                             f(m["recall_en"]), f(m["recall_ko"]), f(m["hard_neg_fpr"]), f(m["hard_fpr_en"]),
                             f(m["hard_fpr_ko"])] + ([f(m["dev_fpr"])] if key == "rules_only" else []))
        head = ["rule", "sensitivity", "pos", "P", "R", "F1", "R en", "R ko", "hard-neg FPR", "FPR en", "FPR ko"]
        o.append(md_table(head + (["dev-neg FPR"] if key == "rules_only" else []), rows))
        rows = []
        for p in PRESETS:
            d = rm[f"decision|{p}"]
            rows.append([p, f(d["block"]["precision"]), f(d["block"]["recall"]), f(d["block"]["fpr"]),
                         f(d["neg_blocked_by_pii"])] + ([f(rm.get(f"dev_any_rule|{p}"))] if key == "rules_only" else []))
        o.append("\nDecision level on the rule set (any reason):\n\n")
        o.append(md_table(["preset", "P block", "R block", "hard-neg FPR block", "hard negs blocked by PII path"]
                          + (["dev negs flagged"] if key == "rules_only" else []), rows))
    if perf_l:
        o.append("\n## Latency: local `guard_core.check` (sequential, default policy)\n")
        o.append(f"Measured {perf_l['date']}, {perf_l['all']['n']} texts after 5 warm-up calls. Milliseconds.\n")
        rows = [["all", perf_l["all"]["n"], perf_l["all"]["p50"], perf_l["all"]["p95"], perf_l["all"]["p99"], "-"]]
        for b, v in perf_l["buckets"].items():
            rows.append([f"len {b}", v["n"], v["p50"], v["p95"], v["p99"], v["mean_chunks"]])
        rows.append(["model called", perf_l["model_called"]["n"], perf_l["model_called"]["p50"], perf_l["model_called"]["p95"], perf_l["model_called"]["p99"], "-"])
        rows.append(["regex short-circuit", perf_l["regex_shortcut"]["n"], perf_l["regex_shortcut"]["p50"], perf_l["regex_shortcut"]["p95"], perf_l["regex_shortcut"]["p99"], "0"])
        o.append(md_table(["bucket", "n", "p50", "p95", "p99", "mean chunks"], rows))
    if perf_a:
        o.append("\n## Latency / throughput: AWS Guard Lambda\n")
        o.append(f"Measured {perf_a['date']} in {perf_a['region']}, {perf_a['total_invocations']} invocations in total "
                 "(10 warm-up). Synthetic texts only. client = boto3 round trip from this laptop; "
                 "reported = `latency_ms` inside the Lambda.\n")
        s = perf_a["sequential"]
        rows = [["sequential", s["client_round_trip_ms"]["n"], s["client_round_trip_ms"]["p50"], s["client_round_trip_ms"]["p95"],
                 s["client_round_trip_ms"]["p99"], s["reported_latency_ms"]["p50"], s["reported_latency_ms"]["p95"],
                 s["reported_latency_ms"]["p99"], "-", s["errors"]]]
        for c, v in perf_a["concurrency"].items():
            rows.append([f"concurrency {c}", v["calls"], v["client_round_trip_ms"]["p50"], v["client_round_trip_ms"]["p95"],
                         v["client_round_trip_ms"]["p99"], v["reported_latency_ms"]["p50"], v["reported_latency_ms"]["p95"],
                         v["reported_latency_ms"]["p99"], v["throughput_rps"], v["errors"]])
        o.append(md_table(["mode", "calls", "client p50", "client p95", "client p99", "reported p50", "reported p95",
                           "reported p99", "throughput rps", "errors"], rows))
    return "".join(o)


def main():
    M = {}
    pii = load("pii")
    if pii:
        M["pii"] = pii_metrics(pii)
    for k in ("rules_only", "rules_default"):
        rows = load(k)
        if rows:
            M[k] = rule_metrics(rows)
    with open(os.path.join(RES, "metrics.json"), "w") as fh:
        json.dump(M, fh, indent=1)

    def jl(name):
        p = os.path.join(RES, name)
        return json.load(open(p)) if os.path.exists(p) else None
    perf_l, perf_a = jl("perf_local.json"), jl("perf_aws.json")
    health = (perf_l or {}).get("health") or {}
    if not health:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "guard"))
        try:
            import guard_core
            health = guard_core.health() or {}
        except Exception:
            health = {}
    body = render(M, counts(), perf_l, perf_a, health)
    out = os.path.join(HERE, "RESULTS.md")
    findings = ""
    if os.path.exists(out):
        old = open(out, encoding="utf-8").read()
        if "\n## Findings" in old:
            findings = old[old.index("\n## Findings"):]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(body + (findings or "\n## Findings\n\n(to be written)\n"))
    print("wrote RESULTS.md and results/metrics.json")


if __name__ == "__main__":
    main()
