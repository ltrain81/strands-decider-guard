"""Build evaluation sets from public Hugging Face datasets -> data/sets/<name>.jsonl (gitignored).

Each line: {"id", "set", "lang", "label": 1|0, "cats": [guard categories], "group", "text"}
  label 1 = contains PII mapped to one of the guard categories ("strong" positive)
  group "weak" = only names / dates / companies / cities etc. (reported separately, not in P/R)

Run:  .venv/bin/python -I datasets.py          (seeded, deterministic)
Prints only counts.
"""
import ast
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hf  # noqa: E402

SEED = 20261012
SETS = os.path.join(hf.DATA, "sets")
MAX_LEN = 4000
N_POS = 200

# dataset label -> guard category (labels not listed are "weak" PII: names, dates, orgs, cities, urls ...)
LABEL_CAT = {
    # resident registration number
    "KR_RRN": "resident_id",
    # government ids
    "ssn": "gov_id", "national_id": "gov_id", "passport_number": "gov_id", "driver_license_number": "gov_id",
    "tax_id": "gov_id", "IDCARDNUM": "gov_id", "SOCIALNUM": "gov_id", "TAXNUM": "gov_id",
    "DRIVERLICENSENUM": "gov_id", "KR_PASSPORT": "gov_id", "KR_DRIVER_LICENSE": "gov_id",
    "certificate_license_number": "gov_id",
    # financial
    "credit_card_number": "financial", "credit_debit_card": "financial", "account_number": "financial",
    "iban": "financial", "bban": "financial", "bank_routing_number": "financial", "cvv": "financial",
    "credit_card_security_code": "financial", "CREDITCARDNUMBER": "financial", "ACCOUNTNUM": "financial",
    "KR_BANK_ACCOUNT": "financial", "CREDIT_CARD": "financial",
    # contact
    "email": "contact", "phone_number": "contact", "street_address": "contact", "fax_number": "contact",
    "EMAIL": "contact", "TELEPHONENUM": "contact", "STREET": "contact", "EMAIL_ADDRESS": "contact",
    "KR_PHONE_NUMBER": "contact", "KR_LOCATION": "contact",
    # health
    "medical_record_number": "health", "health_plan_beneficiary_number": "health", "blood_type": "health",
    "KR_NHIS": "health",
    # credentials
    "password": "credential", "api_key": "credential", "PASSWORD": "credential", "http_cookie": "credential",
    "account_pin": "credential", "pin": "credential",
}

SOURCES = {
    "ai4privacy": ("ai4privacy/pii-masking-400k", "validation"),
    "gretel_finance": ("gretelai/synthetic_pii_finance_multilingual", "test"),
    "nemotron": ("nvidia/Nemotron-PII", "test"),
    "kpii_bench": ("woohyun212/k-pii-bench", "test_track_a"),
    "dolly": ("databricks/databricks-dolly-15k", "train"),
    "code_alpaca": ("sahil2801/CodeAlpaca-20k", "train"),
    "sql_context": ("b-mc2/sql-create-context", "train"),
}


def cats_of(labels):
    return sorted({LABEL_CAT[l] for l in labels if l in LABEL_CAT})


def stratified(rows, n, rng):
    """Pick n rows covering every category roughly equally (round robin), rows: [(cats, item)]."""
    rng.shuffle(rows)
    by = {}
    for i, (cats, _) in enumerate(rows):
        for c in cats:
            by.setdefault(c, []).append(i)
    picked, seen = [], set()
    keys = sorted(by)
    while len(picked) < n and any(by[k] for k in keys):
        for k in keys:
            while by[k] and by[k][-1] in seen:
                by[k].pop()
            if by[k] and len(picked) < n:
                i = by[k].pop()
                seen.add(i)
                picked.append(rows[i][1])
    return picked


def rec(set_name, i, lang, label, cats, group, text):
    return {"id": f"{set_name}-{i}", "set": set_name, "lang": lang, "label": label, "cats": cats,
            "group": group, "text": text}


def build_ai4privacy(rng):
    ds, split = SOURCES["ai4privacy"]
    rows = hf.read(hf.parquet(ds, split), columns=["source_text", "language", "privacy_mask"])
    rows = [r for r in rows if r["language"] == "en" and len(r["source_text"]) <= MAX_LEN]
    pos = [(cats_of([m["label"] for m in r["privacy_mask"]]), r) for r in rows if r["privacy_mask"]]
    strong = stratified([p for p in pos if p[0]], N_POS, rng)
    weak = [r for c, r in pos if not c]
    rng.shuffle(weak)
    neg = [r for r in rows if not r["privacy_mask"]]
    rng.shuffle(neg)
    out = [rec("ai4privacy", i, "en", 1, cats_of([m["label"] for m in r["privacy_mask"]]), "strong", r["source_text"])
           for i, r in enumerate(strong)]
    out += [rec("ai4privacy", f"w{i}", "en", 1, [], "weak", r["source_text"]) for i, r in enumerate(weak[:50])]
    out += [rec("ai4privacy", f"n{i}", "en", 0, [], "neg", r["source_text"]) for i, r in enumerate(neg[:100])]
    return out


def build_gretel(rng):
    ds, split = SOURCES["gretel_finance"]
    rows = hf.read(hf.parquet(ds, split), columns=["generated_text", "language", "pii_spans"])
    rows = [r for r in rows if r["language"] == "English" and len(r["generated_text"]) <= MAX_LEN]
    for r in rows:
        r["spans"] = json.loads(r["pii_spans"] or "[]")
    pos = [(cats_of([s["label"] for s in r["spans"]]), r) for r in rows if r["spans"]]
    strong = stratified([p for p in pos if p[0]], N_POS, rng)
    weak = [r for c, r in pos if not c]
    rng.shuffle(weak)
    neg = [r for r in rows if not r["spans"]]
    rng.shuffle(neg)
    out = [rec("gretel_finance", i, "en", 1, cats_of([s["label"] for s in r["spans"]]), "strong", r["generated_text"])
           for i, r in enumerate(strong)]
    out += [rec("gretel_finance", f"w{i}", "en", 1, [], "weak", r["generated_text"]) for i, r in enumerate(weak[:50])]
    out += [rec("gretel_finance", f"n{i}", "en", 0, [], "neg", r["generated_text"]) for i, r in enumerate(neg[:150])]
    return out


def build_nemotron(rng):
    ds, split = SOURCES["nemotron"]
    rows = hf.read(hf.parquet(ds, split), columns=["text", "spans", "locale"])
    rows = [r for r in rows if len(r["text"]) <= MAX_LEN]
    rng.shuffle(rows)
    rows = rows[:6000]
    for r in rows:
        r["sp"] = ast.literal_eval(r["spans"]) if r["spans"] else []  # literal parsing only, never eval
    pos = [(cats_of([s["label"] for s in r["sp"]]), r) for r in rows if r["sp"]]
    strong = stratified([p for p in pos if p[0]], N_POS, rng)
    weak = [r for c, r in pos if not c]
    rng.shuffle(weak)
    out = [rec("nemotron", i, "en", 1, cats_of([s["label"] for s in r["sp"]]), "strong", r["text"])
           for i, r in enumerate(strong)]
    out += [rec("nemotron", f"w{i}", "en", 1, [], "weak", r["text"]) for i, r in enumerate(weak[:50])]
    return out


def build_kpii(rng):
    ds, split = SOURCES["kpii_bench"]
    rows = hf.read(hf.parquet(ds, split), columns=["text", "entities"])
    rows = [r for r in rows if len(r["text"]) <= MAX_LEN]
    pos = [(cats_of([e["type"] for e in r["entities"]]), r) for r in rows if r["entities"]]
    strong = stratified([p for p in pos if p[0]], N_POS, rng)
    weak = [r for c, r in pos if not c]
    rng.shuffle(weak)
    out = [rec("kpii_bench", i, "ko", 1, cats_of([e["type"] for e in r["entities"]]), "strong", r["text"])
           for i, r in enumerate(strong)]
    out += [rec("kpii_bench", f"w{i}", "ko", 1, [], "weak", r["text"]) for i, r in enumerate(weak[:50])]
    return out


TECH = re.compile(r"\b(python|java|javascript|sql|database|algorithm|api|server|linux|docker|kubernetes|cloud|"
                  r"compiler|function|software|programming|http|json|git|neural|machine learning|cpu|memory)\b", re.I)
QUOTED_NAME = re.compile(r"""["'][A-Z][a-z]+ [A-Z][a-z]+["']""")


def build_dev_public(rng):
    """Developer-style negatives from public sources: tech Q&A (Dolly), code (CodeAlpaca), SQL (sql-create-context)."""
    out = []
    ds, split = SOURCES["dolly"]
    rows = [r for r in hf.read(hf.parquet(ds, split))
            if r["category"] in ("open_qa", "general_qa", "brainstorming", "classification")
            and TECH.search(r["instruction"] + " " + r["response"])]
    rng.shuffle(rows)
    for i, r in enumerate(rows[:40]):
        out.append(rec("dev_public", f"dolly{i}", "en", 0, [], "neg", (r["instruction"] + "\n\n" + r["response"])[:MAX_LEN]))
    ds, split = SOURCES["code_alpaca"]
    rows = [r for r in hf.read(hf.parquet(ds, split)) if len(r["output"]) > 80]
    rng.shuffle(rows)
    for i, r in enumerate(rows[:40]):
        text = r["instruction"] + ("\n" + r["input"] if r["input"] else "") + "\n\n" + r["output"]
        out.append(rec("dev_public", f"code{i}", "en", 0, [], "neg", text[:MAX_LEN]))
    ds, split = SOURCES["sql_context"]
    rows = hf.read(hf.parquet(ds, split), limit=20000)
    rows = [r for r in rows if not QUOTED_NAME.search(r["answer"])]
    rng.shuffle(rows)
    for i, r in enumerate(rows[:30]):
        out.append(rec("dev_public", f"sql{i}", "en", 0, [], "neg", f"{r['context']}\n-- {r['question']}\n{r['answer']}"))
    return out


def write(name, recs):
    os.makedirs(SETS, exist_ok=True)
    with open(os.path.join(SETS, name + ".jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    builders = {"ai4privacy": build_ai4privacy, "gretel_finance": build_gretel, "nemotron": build_nemotron,
                "kpii_bench": build_kpii, "dev_public": build_dev_public}
    meta = {k: hf.info(v[0]) for k, v in SOURCES.items()}
    for name, fn in builders.items():
        recs = fn(random.Random(f"{SEED}-{name}"))
        write(name, recs)
        groups = {}
        for r in recs:
            groups[r["group"]] = groups.get(r["group"], 0) + 1
        cats = {}
        for r in recs:
            for c in r["cats"]:
                cats[c] = cats.get(c, 0) + 1
        print(name, groups, cats)
    with open(os.path.join(SETS, "sources.json"), "w") as f:
        json.dump(meta, f, indent=1)


if __name__ == "__main__":
    main()
