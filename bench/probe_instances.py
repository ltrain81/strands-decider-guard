"""Measure strands-decider latency/throughput on cheaper instance types, then terminate them.

Launches temporary instances (tag Name=decider-probe-<type>) next to the deployed host: same VPC public subnet,
security group, instance profile and user data (installs strands-decider and starts the server). GPU and x86 CPU
types use the deployed GPU AMI; arm64 types use Ubuntu 22.04 arm64. Each instance runs a stdlib benchmark through
SSM against its own decider (synthetic text without personal data), and everything is terminated in `finally`.

Results -> results/probe_<type>.json and a summary table on stdout.

Run:  .venv/bin/python -I probe_instances.py --types g6f.2xlarge,g4dn.xlarge,c8g.2xlarge [--region ap-northeast-2]
"""
import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RES = os.path.join(HERE, "results")
UBUNTU_ARM = "/aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id"

# Runs on the instance (python3 stdlib). Same 4 questions as guard_core.QUESTIONS; text has no personal data.
BENCH = r'''
import json, os, time, urllib.request, statistics, concurrent.futures as cf
CONCURRENCY = os.environ.get("PROBE_CONCURRENCY") == "1"
Q = json.loads(open("/tmp/q.json").read())
WORDS = "the order service retries failed payments with exponential backoff and writes metrics to the warehouse table".split()
def text(n):
    out = []
    while sum(len(w) + 1 for w in out) < n:
        out.append(WORDS[len(out) % len(WORDS)])
    return " ".join(out)[:n]
def ask(t):
    body = json.dumps({"state": t, "questions": Q}).encode()
    t0 = time.time()
    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/v1/systemone", body, {"content-type": "application/json"}), timeout=120).read()
    return (time.time() - t0) * 1000
def pct(v, p):
    v = sorted(v); return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 1)
out = {}
for _ in range(3): ask(text(200))
for n in (200, 1500):
    lat = [ask(text(n)) for _ in range(25)]
    out[f"seq_{n}"] = {"p50": pct(lat, 50), "p95": pct(lat, 95)}
for w in ((4,) if CONCURRENCY else ()):
    t0 = time.time()
    with cf.ThreadPoolExecutor(w) as ex:
        lat = list(ex.map(ask, [text(800)] * 40))
    out[f"conc_{w}"] = {"rps": round(40 / (time.time() - t0), 2), "p50": pct(lat, 50)}
out["health"] = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/health").read())
print("RESULT " + json.dumps(out))
'''


def outputs():
    with open(os.path.join(REPO, "outputs.json")) as f:
        return next(iter(json.load(f).values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", required=True)
    ap.add_argument("--region", default="ap-northeast-2")
    ap.add_argument("--baseline", action="store_true", help="also measure the deployed host")
    args = ap.parse_args()
    ec2, ssm = boto3.client("ec2", region_name=args.region), boto3.client("ssm", region_name=args.region)
    host = ec2.describe_instances(InstanceIds=[outputs()["DeciderInstanceId"]])["Reservations"][0]["Instances"][0]
    user_data = ec2.describe_instance_attribute(InstanceId=host["InstanceId"], Attribute="userData")["UserData"]["Value"]
    user_data = base64.b64decode(user_data).decode()
    arm_ami = ssm.get_parameter(Name=UBUNTU_ARM)["Parameter"]["Value"]
    arch = {t["InstanceType"]: t["ProcessorInfo"]["SupportedArchitectures"][0]
            for t in ec2.describe_instance_types(InstanceTypes=args.types.split(","))["InstanceTypes"]}
    sys.path.insert(0, os.path.join(REPO, "guard"))
    import guard_core
    questions = json.dumps(guard_core.QUESTIONS)
    os.makedirs(RES, exist_ok=True)

    launched = {}
    try:
        for t in args.types.split(","):
            r = ec2.run_instances(
                ImageId=arm_ami if arch[t] == "arm64" else host["ImageId"], InstanceType=t, MinCount=1, MaxCount=1,
                SubnetId=host["SubnetId"], SecurityGroupIds=[g["GroupId"] for g in host["SecurityGroups"]],
                IamInstanceProfile={"Arn": host["IamInstanceProfile"]["Arn"]}, UserData=user_data,
                MetadataOptions={"HttpTokens": "required"},
                BlockDeviceMappings=[{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 80, "VolumeType": "gp3", "Encrypted": True}}],
                TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": f"decider-probe-{t}"}]}])
            launched[t] = r["Instances"][0]["InstanceId"]
            print(f"launched {t}: {launched[t]}", flush=True)

        def probe(t, iid):
            t0 = time.time()
            b64 = lambda x: base64.b64encode(x.encode()).decode()   # no shell quoting issues (the questions contain apostrophes)
            script = (f"echo {b64(questions)} | base64 -d > /tmp/q.json && echo {b64(BENCH)} | base64 -d > /tmp/bench.py && "
                      "for i in $(seq 1 180); do curl -sf localhost:8000/health >/dev/null && break; sleep 10; done; "
                      f"PROBE_CONCURRENCY={0 if iid == host['InstanceId'] else 1} python3 /tmp/bench.py")  # never load the live host
            cid = None
            while time.time() - t0 < 2400:   # SSM agent registration + install + model download
                try:
                    cid = ssm.send_command(InstanceIds=[iid], DocumentName="AWS-RunShellScript",
                                           Parameters={"commands": [script], "executionTimeout": ["2400"]})["Command"]["CommandId"]
                    break
                except ssm.exceptions.InvalidInstanceId:
                    time.sleep(15)
            if not cid:
                return t, {"error": "SSM never came online"}
            while True:
                time.sleep(20)
                try:
                    inv = ssm.get_command_invocation(CommandId=cid, InstanceId=iid)
                except ssm.exceptions.InvocationDoesNotExist:
                    continue
                if inv["Status"] in ("Success", "Failed", "TimedOut", "Cancelled"):
                    break
            line = [l for l in inv["StandardOutputContent"].splitlines() if l.startswith("RESULT ")]
            res = json.loads(line[-1][7:]) if line else {"error": inv["Status"], "stderr": inv["StandardErrorContent"][-400:]}
            res["ready_minutes"] = round((time.time() - t0) / 60, 1)
            with open(os.path.join(RES, f"probe_{t.split()[0]}.json"), "w") as f:
                json.dump(res, f, indent=2)
            print(f"done {t}: {json.dumps(res)[:300]}", flush=True)
            return t, res

        targets = dict(launched)
        if args.baseline:  # the deployed host, measured the same way (not launched, not terminated)
            targets[f"{host['InstanceType']} (deployed)"] = host["InstanceId"]
        with ThreadPoolExecutor(len(targets)) as ex:
            results = dict(ex.map(lambda kv: probe(*kv), targets.items()))
    finally:
        if launched:   # retry: a network hiccup here once left five probe instances running
            for attempt in range(30):
                try:
                    ec2.terminate_instances(InstanceIds=list(launched.values()))
                    print("terminated:", ", ".join(launched.values()), flush=True)
                    break
                except Exception as e:
                    print(f"terminate failed ({e}); retrying", flush=True)
                    time.sleep(10)
            else:
                print("COULD NOT TERMINATE, do it by hand:", " ".join(launched.values()), file=sys.stderr)

    print("\n| type | device | seq p50 (200 chars) | seq p50 (1500 chars) | p95 (1500) | 4 parallel req/s |")
    print("|---|---|---|---|---|---|")
    for t, r in results.items():
        if "error" in r:
            print(f"| {t} | error: {r['error']} | | | | |")
        else:
            print(f"| {t} | {r['health'].get('device')} | {r['seq_200']['p50']} | {r['seq_1500']['p50']} | {r['seq_1500']['p95']} | {r.get('conc_4', {}).get('rps', '-')} |")


if __name__ == "__main__":
    main()
