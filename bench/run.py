"""Accuracy runs of guard_core.check over the evaluation sets.

Model answers are memoised per (chunk, question set) so the three presets reuse one model pass; the
decision logic itself is always guard_core.check (unchanged). The cache stores only a hash of the chunk.
Per-sample results (ids, labels, decisions, finding types - no text) -> results/<experiment>.jsonl

Run:  .venv/bin/python -I run.py [pii|rules_only|rules_default|all] [--workers 6]
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "guard"))
import guard_core as g  # noqa: E402
from rules import RULES  # noqa: E402

SETS = os.path.join(HERE, "data", "sets")
RES = os.path.join(HERE, "results")
PRESETS = ("lenient", "balanced", "strict")
PII_SETS = ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth", "dev_public", "dev_synth"]
CATS = [c["id"] for c in g.CATEGORIES]

# ------------------------------------------------------------------ memoised model calls
_orig_ask = g.ask_decider
_cache, _lock = {}, threading.Lock()
CACHE_FILE = os.path.join(RES, "answer_cache.jsonl")
STATS = {"calls": 0, "hits": 0}


def _key(state, questions):
    return hashlib.sha256((state + "\0" + json.dumps(questions, sort_keys=True)).encode()).hexdigest()


def cached_ask(state, url=None, timeout=20, questions=None):
    k = _key(state, questions or g.QUESTIONS)
    with _lock:
        if k in _cache:
            STATS["hits"] += 1
            return json.loads(_cache[k])
    for attempt in range(40):  # tolerate a decider restart (up to ~6 minutes)
        try:
            ans = _orig_ask(state, url, timeout=60, questions=questions)
            break
        except Exception:
            if attempt == 39:
                raise
            time.sleep(min(2 + attempt * 2, 10))
    s = json.dumps(ans)
    with _lock:
        STATS["calls"] += 1
        _cache[k] = s
        with open(CACHE_FILE, "a") as f:
            f.write(json.dumps({"k": k, "a": ans}) + "\n")
    return json.loads(s)


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            for line in f:
                try:
                    j = json.loads(line)
                    _cache[j["k"]] = json.dumps(j["a"])
                except ValueError:
                    pass


g.ask_decider = cached_ask

# ------------------------------------------------------------------ helpers


def load(name):
    with open(os.path.join(SETS, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def attribution(res):
    """Which component produced the final decision: regex (strong pattern, model not consulted), model, rule."""
    d = res["decision"]
    if d == "allow":
        return None
    fs = res["findings"]
    if any(f["source"] == "regex" and f.get("strong") and f["action"] == d for f in fs):
        return "regex"
    weak = any(f["source"] == "regex" and not f.get("strong") for f in fs)
    srcs = {f["source"] for f in fs if f["source"] != "regex"}
    if "decider" in srcs and "rule" in srcs:
        return "model+rule"
    if "rule" in srcs:
        return "rule"
    return "regex+model" if weak else "model"


def slim(f):
    keep = ("source", "type", "category", "strong", "action", "p", "kind_confidence", "p_pii", "p_named", "chunk")
    return {k: f[k] for k in keep if k in f}


def run_one(sample, policy):
    res = g.check(sample["text"], policy=policy)
    return {"id": sample["id"], "set": sample["set"], "lang": sample["lang"], "label": sample["label"],
            "cats": sample["cats"], "group": sample["group"], "kind": sample.get("kind"), "rule": sample.get("rule"),
            "len": len(sample["text"]), "decision": res["decision"], "by": attribution(res),
            "findings": [slim(f) for f in res["findings"]], "chunks": res["chunks_scanned"]}


def run_experiment(name, jobs, workers):
    """jobs: [(sample, policy, tag-dict)]"""
    out_path = os.path.join(RES, name + ".jsonl")
    t0 = time.time()
    rows = []

    def work(job):
        s, pol, tag = job
        r = run_one(s, pol)
        r.update(tag)
        return r

    with ThreadPoolExecutor(workers) as ex:
        for i, r in enumerate(ex.map(work, jobs)):
            rows.append(r)
            if (i + 1) % 200 == 0:
                print(f"  {name}: {i + 1}/{len(jobs)} ({time.time() - t0:.0f}s, model calls {STATS['calls']})", flush=True)
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{name}: {len(rows)} rows in {time.time() - t0:.0f}s; model calls {STATS['calls']}, cache hits {STATS['hits']}")


def rule_policy(sens, pii_default):
    pol = {"sensitivity": sens,
           "custom_rules": [{"id": r["id"], "name": r["name"], "question": r["question"], "action": "block",
                             "sensitivity": sens} for r in RULES]}
    if not pii_default:
        pol["categories"] = {c: "allow" for c in CATS}
    return pol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("which", nargs="?", default="all")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    load_cache()
    if not g.health():
        sys.exit("decider is not reachable at " + g.DECIDER_URL)
    if a.which in ("pii", "all"):
        samples = [s for n in PII_SETS for s in load(n)]
        jobs = [(s, {"sensitivity": p}, {"preset": p}) for p in PRESETS for s in samples]
        run_experiment("pii", jobs, a.workers)
    if a.which in ("rules_only", "all"):
        samples = load("rules") + load("dev_public") + load("dev_synth")
        jobs = [(s, rule_policy(p, False), {"preset": p}) for p in PRESETS for s in samples]
        run_experiment("rules_only", jobs, a.workers)
    if a.which in ("rules_default", "all"):
        samples = load("rules")
        jobs = [(s, rule_policy(p, True), {"preset": p}) for p in PRESETS for s in samples]
        run_experiment("rules_default", jobs, a.workers)


if __name__ == "__main__":
    main()
