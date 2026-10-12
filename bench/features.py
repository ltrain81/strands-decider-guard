"""Per-sample features from cached model answers, for fast policy tuning without new model calls.

For every sample: the regex hits (strong / weak types) and, per chunk, the decider's answers to the
guard questions. Answers come from results/answer_cache.jsonl (filled by run.py); a missing answer is
fetched from the local decider once and cached. Output: results/features.jsonl (no text).

Run:  .venv/bin/python -I features.py [--sets ai4privacy,...] [--questions default|extended]
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(REPO, "guard")]
import guard_core as g  # noqa: E402

SETS = os.path.join(HERE, "data", "sets")
RES = os.path.join(HERE, "results")
CACHE = os.path.join(RES, "answer_cache.jsonl")
ALL_SETS = ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth", "dev_public", "dev_synth", "private_life"]

_cache = {}


def load_cache():
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            for line in f:
                try:
                    j = json.loads(line)
                    _cache[j["k"]] = j["a"]
                except ValueError:
                    pass


def ask(state, questions):
    k = hashlib.sha256((state + "\0" + json.dumps(questions, sort_keys=True)).encode()).hexdigest()
    if k not in _cache:
        _cache[k] = g.ask_decider(state, None, timeout=60, questions=questions)
        with open(CACHE, "a") as f:
            f.write(json.dumps({"k": k, "a": _cache[k]}) + "\n")
    return _cache[k]


def split_of(sample_id):
    """Stable 50/50 split: thresholds are chosen on 'tune' and reported on 'holdout'."""
    return "tune" if int(hashlib.sha256(sample_id.encode()).hexdigest(), 16) % 2 == 0 else "holdout"


def features(rec, questions):
    text = rec["text"]
    policy = g.normalize_policy(None)
    hits = g.scan_patterns(text, policy)
    parts, truncated = g.chunks(text)
    chunks = []
    for lo, part in parts:
        if len(text.strip()) < 8:
            break
        a = ask(part, questions)
        chunks.append({"probs": a["kind"]["probabilities"], "noul": {k: v["noul"] for k, v in a.items() if "noul" in v},
                       "weak": sorted({h["type"] for h in hits if not h["strong"] and lo <= h["pos"] < lo + len(part)})})
    return {k: rec.get(k) for k in ("id", "set", "lang", "label", "cats", "group", "kind")} | {
        "strong": sorted({h["type"] for h in hits if h["strong"]}), "weak": sorted({h["type"] for h in hits if not h["strong"]}),
        "chunks": chunks, "len": len(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default=",".join(ALL_SETS))
    ap.add_argument("--variant", default="V0", help="question set from variants.py")
    ap.add_argument("--split", default="all", choices=["all", "tune", "holdout"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    from variants import VARIANTS
    questions = VARIANTS[args.variant]
    out_name = args.out or f"features_{args.variant}_{args.split}.jsonl"
    load_cache()
    before = len(_cache)
    out = []
    for s in args.sets.split(","):
        path = os.path.join(SETS, f"{s}.jsonl")
        if not os.path.exists(path):
            print(f"skip {s}: no data/sets/{s}.jsonl")
            continue
        with open(path) as f:
            recs = [json.loads(l) for l in f]
        for r in recs:
            if args.split != "all" and split_of(r["id"]) != args.split:
                continue
            out.append(features(r, questions))
        print(f"{s}: {len(recs)} samples", flush=True)
    with open(os.path.join(RES, out_name), "w") as f:
        for row in out:
            f.write(json.dumps(row) + "\n")
    print(f"{len(out)} samples, {len(_cache) - before} new model calls -> results/{out_name}")


if __name__ == "__main__":
    main()
