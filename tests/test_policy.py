#!/usr/bin/env python3
"""Run the guard policy on the synthetic samples. Usage: test_policy.py [--holdout] [--sensitivity=strict] [decider_url]"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "guard")]
import guard_core
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if "--holdout" in sys.argv:
    from holdout import PII, CLEAN
    SECRET = []
else:
    from samples import PII, SECRET, CLEAN

url = args[0] if args else None
sens = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--sensitivity=")), "balanced")
policy = {"sensitivity": sens}
bad, lat = 0, []
for label, texts, want in (("pii", PII, {"block"}), ("secret", SECRET, {"block"}), ("clean", CLEAN, {"allow"})):
    for t in texts:
        r = guard_core.check(t, url, policy)
        lat.append(r["latency_ms"])
        ok = r["decision"] in want or (label != "clean" and r["decision"] == "ask")
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label:6} -> {r['decision']:5} {r['latency_ms']:6.0f}ms  {t[:50]!r}  {'; '.join(r['reasons'])[:110]}")
lat.sort()
print(f"\n[{sens}] {bad} unexpected (ask counts as caught for pii/secret). median {lat[len(lat)//2]:.0f}ms")
sys.exit(1 if bad else 0)
