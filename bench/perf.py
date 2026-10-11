"""Latency / throughput benchmark.

  local : guard_core.check (default policy) against the local decider, sequential, >=200 texts bucketed by length
  aws   : the deployed Guard Lambda (outputs.json), sequential + concurrency 4 and 8

The local decider must not receive concurrent requests (see README caveats), so do not run this while run.py runs.
Results (numbers only) -> results/perf_local.json, results/perf_aws.json

Run:  .venv/bin/python -I perf.py local
      .venv/bin/python -I perf.py aws [--seq 220 --conc 4,8 --per 100]
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "guard"))
import guard_core as g  # noqa: E402

SETS = os.path.join(HERE, "data", "sets")
RES = os.path.join(HERE, "results")
SEED = 20261012
BUCKETS = [("<200", 0, 200), ("200-1500", 200, 1500), (">1500", 1500, 10 ** 9)]


def load(name):
    with open(os.path.join(SETS, name + ".jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def summary(xs):
    return {"n": len(xs), "p50": pct(xs, 50), "p95": pct(xs, 95), "p99": pct(xs, 99),
            "mean": round(sum(xs) / len(xs), 1) if xs else None, "max": round(max(xs), 1) if xs else None}


def pick_texts(per_bucket, names, rng):
    pool = [s["text"] for n in names for s in load(n)]
    rng.shuffle(pool)
    out = []
    for label, lo, hi in BUCKETS:
        out += [(label, t) for t in pool if lo <= len(t) < hi][:per_bucket]
    return out


def local(args):
    rng = random.Random(SEED)
    texts = pick_texts(args.per_bucket, ["ai4privacy", "gretel_finance", "nemotron", "kpii_bench", "ko_synth",
                                         "dev_public", "dev_synth", "rules"], rng)
    for _, t in texts[:5]:  # warm-up
        g.check(t)
    rows = []
    for label, t in texts:
        t0 = time.perf_counter()
        r = g.check(t)
        rows.append({"bucket": label, "ms": (time.perf_counter() - t0) * 1000, "chunks": r["chunks_scanned"],
                     "decision": r["decision"]})
    out = {"health": {k: v for k, v in g.health().items() if k in ("model", "device", "num_slots")},
           "all": summary([r["ms"] for r in rows]),
           "model_called": summary([r["ms"] for r in rows if r["chunks"] > 0]),
           "regex_shortcut": summary([r["ms"] for r in rows if r["chunks"] == 0]),
           "buckets": {b: {**summary([r["ms"] for r in rows if r["bucket"] == b]),
                           "mean_chunks": round(sum(r["chunks"] for r in rows if r["bucket"] == b)
                                                / max(1, sum(1 for r in rows if r["bucket"] == b)), 2)}
                       for b, _, _ in BUCKETS},
           "date": time.strftime("%Y-%m-%d %H:%M %Z")}
    with open(os.path.join(RES, "perf_local.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


def aws(args):
    import boto3
    from botocore.config import Config
    with open(os.path.join(REPO, "outputs.json")) as f:
        o = next(iter(json.load(f).values()))
    fn, region = o["GuardFunctionName"], o["Region"]
    client = boto3.client("lambda", region_name=region,
                          config=Config(max_pool_connections=16, retries={"max_attempts": 0}, read_timeout=70))
    rng = random.Random(SEED)
    # synthetic texts only (no public-dataset text is sent to the cloud)
    pool = [s["text"] for n in ("dev_synth", "ko_synth", "rules") for s in load(n)]
    rng.shuffle(pool)

    def call(text):
        t0 = time.perf_counter()
        try:
            r = client.invoke(FunctionName=fn, Payload=json.dumps({"text": text, "client": "bench"}).encode())
            p = json.loads(r["Payload"].read())
            ms = (time.perf_counter() - t0) * 1000
            if r.get("FunctionError") or "decision" not in p:
                return {"ok": False, "rt": ms, "err": r.get("FunctionError") or "no decision"}
            res = p.get("results") or [{}]
            return {"ok": True, "rt": ms, "lat": res[0].get("latency_ms"), "decision": p["decision"],
                    "len": len(text)}
        except Exception as e:  # count, do not crash
            return {"ok": False, "rt": (time.perf_counter() - t0) * 1000, "err": type(e).__name__}

    calls = 0
    for t in pool[:10]:  # warm-up (cold start + decider warm)
        call(t)
        calls += 1
    seq = []
    for i in range(args.seq):
        seq.append(call(pool[i % len(pool)]))
    calls += args.seq
    ok = [r for r in seq if r["ok"]]
    out = {"function": fn.split("-")[0] + "-GuardFn", "region": region,
           "sequential": {"client_round_trip_ms": summary([r["rt"] for r in ok]),
                          "reported_latency_ms": summary([r["lat"] for r in ok if r["lat"] is not None]),
                          "errors": len(seq) - len(ok)},
           "concurrency": {}}
    for c in [int(x) for x in args.conc.split(",")]:
        texts = [pool[(i * 7 + c) % len(pool)] for i in range(args.per)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(c) as ex:
            rs = list(ex.map(call, texts))
        wall = time.perf_counter() - t0
        calls += args.per
        ok = [r for r in rs if r["ok"]]
        errs = {}
        for r in rs:
            if not r["ok"]:
                errs[r["err"]] = errs.get(r["err"], 0) + 1
        out["concurrency"][str(c)] = {"calls": len(rs), "wall_s": round(wall, 1), "throughput_rps": round(len(ok) / wall, 2),
                                      "client_round_trip_ms": summary([r["rt"] for r in ok]),
                                      "reported_latency_ms": summary([r["lat"] for r in ok if r["lat"] is not None]),
                                      "errors": len(rs) - len(ok), "error_types": errs}
    out["total_invocations"] = calls
    out["date"] = time.strftime("%Y-%m-%d %H:%M %Z")
    with open(os.path.join(RES, "perf_aws.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["local", "aws"])
    ap.add_argument("--per-bucket", type=int, default=80)
    ap.add_argument("--seq", type=int, default=220)
    ap.add_argument("--conc", default="4,8")
    ap.add_argument("--per", type=int, default=100)
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    local(a) if a.mode == "local" else aws(a)
