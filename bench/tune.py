"""Pick guard thresholds per sensitivity preset from cached features, then report them on the held-out half.

The decision rule mirrors guard_core.judge_chunk, with two extra paths that the miss analysis pointed to:
  * weak-pattern path: a phone/email/passport/... regex hit blocks when the sensitive-category mass is at least `weak_ps`
    (today it also needs the model's real-PII answer above `pattern`)
  * named-person path: a named person plus a moderately sensitive category (`named_cat`) blocks, below the main `cat` bar
For each preset the grid search maximises recall subject to a false-positive cap on all negatives and, separately, on
developer-style text; F1 breaks ties. Thresholds are chosen on the 'tune' split only.

Run:  .venv/bin/python -I tune.py --variant V1            # search on tune, write results/tuned_<variant>.json
      .venv/bin/python -I tune.py --variant V1 --report   # evaluate the saved thresholds on the holdout split
"""
import argparse
import itertools
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
CAPS = {"lenient": 0.01, "balanced": 0.025, "strict": 0.05}   # on false positives the thresholds control (not strong regex)
DEV_SETS = ("dev_public", "dev_synth")
GRID = {
    "cat": [0.5, 0.6, 0.7, 0.8, 0.9],
    "named": [0.35, 0.5, 0.65],
    "block": [0.6, 0.75, 0.85],
    "ask": [0.5],
    "pattern": [0.2, 0.3],
    "weak_ps": [None, 0.15, 0.3, 0.45],
    "named_cat": [None, 0.3, 0.4, 0.5],
    "cred_real": [0.0, 0.3, 0.4],      # a credential verdict also needs the real-value answer (placeholders like ${DB_PASSWORD})
}


def chunk_vals(c):
    probs = c["probs"]
    kinds = [k for k in probs if k != "none"]
    n = c["noul"]
    p = max(n.get("about_person", 0), n.get("real_values", 0), n.get("record", 0))
    return probs, kinds, sum(probs[k] for k in kinds), p, n.get("named_person", 0)


def decide(f, t):
    if f["strong"]:
        return "block"
    best = "allow"
    for c in f["chunks"]:
        probs, kinds, ps, p, named = chunk_vals(c)
        if probs.get("credential", 0) >= t["cat"] and max(kinds, key=probs.get) == "credential":
            if p >= t.get("cred_real", 0):
                return "block"
            continue
        if t["weak_ps"] is not None and c["weak"] and ps >= t["weak_ps"]:
            return "block"
        if t["named_cat"] is not None and named >= t["named"] and ps >= t["named_cat"]:
            return "block"
        if ps < t["cat"]:
            continue
        if named >= t["named"] or (c["weak"] and p >= t["pattern"]) or p >= t["block"]:
            return "block"
        if p >= t["ask"]:
            best = "ask"
    return best


def metrics(F, t):
    pos = [f for f in F if f["label"] == 1 and f.get("group") != "weak"]
    neg = [f for f in F if f["label"] == 0]
    dev = [f for f in neg if f["set"] in DEV_SETS]
    d = {f["id"]: decide(f, t) for f in pos + neg}
    tp = sum(d[f["id"]] == "block" for f in pos)
    fp = sum(d[f["id"]] == "block" for f in neg)
    model_fp = [f for f in neg if d[f["id"]] == "block" and not f["strong"]]
    out = {"recall": tp / len(pos), "fpr": fp / len(neg), "dev_fpr": sum(d[f["id"]] == "block" for f in dev) / max(1, len(dev)),
           "model_fpr": len(model_fp) / len(neg), "model_dev_fpr": sum(f["set"] in DEV_SETS for f in model_fp) / max(1, len(dev)),
           "precision": tp / (tp + fp) if tp + fp else 0, "n_pos": len(pos), "n_neg": len(neg)}
    out["f1"] = 2 * out["precision"] * out["recall"] / (out["precision"] + out["recall"]) if tp else 0
    for lang in ("en", "ko"):
        lp = [f for f in pos if f["lang"] == lang]
        ln = [f for f in neg if f["lang"] == lang]
        out[f"recall_{lang}"] = sum(d[f["id"]] == "block" for f in lp) / max(1, len(lp))
        out[f"fpr_{lang}"] = sum(d[f["id"]] == "block" for f in ln) / max(1, len(ln))
    cats = {c for f in pos for c in (f.get("cats") or [])}
    out["recall_by_cat"] = {c: round(sum(d[f["id"]] == "block" for f in pos if c in (f.get("cats") or [])) /
                                     max(1, sum(c in (f.get("cats") or []) for f in pos)), 3) for c in sorted(cats)}
    return out


def load(variant, split):
    with open(os.path.join(RES, f"features_{variant}_{split}.jsonl")) as f:
        return [json.loads(l) for l in f]


def search(F):
    keys = list(GRID)
    best = {}
    for combo in itertools.product(*(GRID[k] for k in keys)):
        t = dict(zip(keys, combo))
        if t["named_cat"] is not None and t["named_cat"] >= t["cat"]:
            continue
        m = metrics(F, t)
        for preset, cap in CAPS.items():
            if m["model_fpr"] <= cap and m["model_dev_fpr"] <= cap:
                cur = best.get(preset)
                if cur is None or (m["recall"], m["f1"]) > (cur[1]["recall"], cur[1]["f1"]):
                    best[preset] = (t, m)
    return best


def fmt(m):
    return (f"R {100 * m['recall']:.1f} (en {100 * m['recall_en']:.1f}, ko {100 * m['recall_ko']:.1f}) | "
            f"P {100 * m['precision']:.1f} | FPR {100 * m['fpr']:.1f} (model {100 * m['model_fpr']:.1f}; dev {100 * m['dev_fpr']:.1f}, "
            f"dev model {100 * m['model_dev_fpr']:.1f}) | F1 {100 * m['f1']:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="V1")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    path = os.path.join(RES, f"tuned_{args.variant}.json")
    if args.report:
        with open(path) as f:
            chosen = json.load(f)
        H = load(args.variant, "holdout")
        print(f"holdout ({args.variant}, {len(H)} samples)")
        out = {}
        for preset, t in chosen.items():
            m = metrics(H, t)
            out[preset] = m
            print(f"  {preset:9} {fmt(m)}")
        with open(os.path.join(RES, f"holdout_{args.variant}.json"), "w") as f:
            json.dump(out, f, indent=2)
        return
    F = load(args.variant, "tune")
    best = search(F)
    print(f"tune ({args.variant}, {len(F)} samples)")
    for preset, (t, m) in best.items():
        print(f"  {preset:9} {fmt(m)}  <- {t}")
    with open(path, "w") as f:
        json.dump({p: t for p, (t, m) in best.items()}, f, indent=2)


if __name__ == "__main__":
    main()
