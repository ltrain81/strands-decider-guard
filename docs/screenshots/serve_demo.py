#!/usr/bin/env python3
"""Start the policy console on synthetic demo data for screenshots (docs/screenshots/capture.mjs).

Builds a throwaway home with a saved policy history, the first rule template from admin/web/samples.js,
evidence capture on, ~300 synthetic decisions over the last day, a few evidence files and a mocked Alerts
status (local mode has no CloudWatch). Texts come from the repo's synthetic demo data (demo/en, samples.js)
at runtime. Needs a local decider on 127.0.0.1:8000 for the Test tab.

Run:  python3 docs/screenshots/serve_demo.py [--port 8790]
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8790)
args = ap.parse_args()

js = open(os.path.join(ROOT, "admin", "web", "samples.js"), encoding="utf-8").read()
en_block = js[js.index("en: ["):js.index("ko: [")]
template = dict(zip(("name", "question"), re.findall(r"(?:name|question): ['\"](.+?)['\"](?:,| })", en_block)[:2]))
samples = re.findall(r"text: '(.+?)' }", js[js.index("const SAMPLES"):])
texts = {"health": open(os.path.join(ROOT, "demo", "en", "support_ticket.txt")).read().strip(),
         "contact": open(os.path.join(ROOT, "demo", "en", "customers.csv")).read().strip(),
         "rule": next(s for s in samples if "March" in s)}

home = tempfile.mkdtemp(prefix="decider-console-demo-")
os.makedirs(os.path.join(home, "evidence"))
sys.argv = ["dev_server", "--home", home, "--no-open", "--port", str(args.port)]
sys.path.insert(0, os.path.join(ROOT, "admin"))
import dev_server  # noqa: E402  (parses sys.argv and imports the API)

api = dev_server.handler


def put(policy):
    api.handler({"requestContext": {"http": {"method": "PUT"}}, "rawPath": "/api/policy", "headers": {},
                 "body": json.dumps({"policy": policy})})


rule = {"id": "r1", "name": template["name"], "question": template["question"], "action": "block", "sensitivity": "balanced"}
put({"sensitivity": "strict"})
put({"sensitivity": "balanced", "custom_rules": [rule], "allow": {"email_domains": ["acme-corp.com"]},
     "message": "Mask customer data before use. Questions: #privacy-help", "evidence": "blocked"})

random.seed(7)
now = dt.datetime.now()
kinds = [(["email", "phone_intl"], "model_pattern", "contact"), (["kr_resident_id"], "pattern", None),
         (["health"], "model", "health"), (["private_life"], "model", None), (["contact"], "model", "contact"),
         ([f"rule:{template['name']}"], "rule", "rule")]
with open(os.path.join(home, "audit.log"), "w") as f:
    for i in range(320):
        t = now - dt.timedelta(minutes=random.randint(0, 24 * 60 - 1))
        flagged = random.random() < 0.28
        types, basis, key = random.choice(kinds) if flagged else ([], None, None)
        decision = ("ask" if random.random() < 0.15 else "block") if flagged else "allow"
        ev = None
        if key and random.random() < 0.6:
            ev = f"demo{i}"
            with open(os.path.join(home, "evidence", ev + ".json"), "w") as e:
                json.dump({"ts": t.isoformat(timespec="seconds"), "client": "claude", "decision": decision,
                           "items": [{"source": "file:notes.md", "text": texts[key], "truncated": False,
                                      "decision": decision, "basis": basis, "reasons": []}]}, e)
            ev = "local/" + ev
        f.write(json.dumps({"ts": t.strftime("%Y-%m-%dT%H:%M:%S"), "agent": random.choice(["claude", "claude", "codex"]),
                            "event": "PreToolUse", "tool": random.choice(["Read", "Bash", "Write"]), "decision": decision,
                            "types": types, "sources": [random.choice(["file:notes.md", "bash", "prompt"])],
                            "ms": max(40, int(random.gauss(260, 70))), "basis": basis, "evidence": ev}) + "\n")

domain = "example.com"
api.alerts.status = lambda: {
    "available": True,
    "emails": [{"email": f"oncall@{domain}", "status": "confirmed"}, {"email": f"privacy@{domain}", "status": "pending"}],
    "rules": {"guard_down": {"enabled": True, "state": "OK"}, "guard_errors": {"enabled": True, "state": "OK"},
              "block_spike": {"enabled": True, "threshold": 20, "state": "INSUFFICIENT_DATA"},
              "latency": {"enabled": False, "threshold_ms": 3000, "state": None}}}

import http.server  # noqa: E402

print(f"demo console: http://127.0.0.1:{args.port}  (data in {home})", flush=True)
http.server.ThreadingHTTPServer(("127.0.0.1", args.port), dev_server.H).serve_forever()
