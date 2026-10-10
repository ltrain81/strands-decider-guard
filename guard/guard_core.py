"""PII / secret guard: fast regex rules + strands-decider judgement.

Stdlib only. Shared by the AWS Lambda (lambda_handler.py) and the hook's local mode,
so the same policy runs everywhere. Never returns or logs raw matched values: findings
carry masked samples only.
"""
import json
import os
import re
import time
import urllib.request

DECIDER_URL = os.environ.get("DECIDER_URL", "http://127.0.0.1:8000")
CHUNK_CHARS = int(os.environ.get("GUARD_CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = 150
MAX_CHUNKS = int(os.environ.get("GUARD_MAX_CHUNKS", "16"))
CAT_CONF = float(os.environ.get("GUARD_CAT_CONF", "0.8"))   # category must be this confident to count
BLOCK_P = float(os.environ.get("GUARD_BLOCK_P", "0.5"))     # P(real PII values) to block
ASK_P = float(os.environ.get("GUARD_ASK_P", "0.4"))         # P(real PII values) to ask the user
PATTERN_P = 0.3                                             # with a weak regex hit, this P is enough to block

SEVERITY = {"allow": 0, "ask": 1, "block": 2}


def _luhn(digits):
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total, alt = total + n, not alt
    return total % 10 == 0


def _card(m):
    d = re.sub(r"\D", "", m.group(0))
    return 13 <= len(d) <= 19 and d[0] in "3456" and _luhn(d)


# (name, regex, strong, validator). Strong hits block on their own; weak hits need the model to agree.
PATTERNS = [
    ("kr_resident_id", re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s?-\s?[1-8]\d{6}(?!\d)"), True, None),
    ("card_number", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), True, _card),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), True, None),
    ("aws_secret_key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}"), True, None),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"), True, None),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), False, None),
    ("kr_mobile", re.compile(r"(?<!\d)01[016789][ .-]?\d{3,4}[ .-]?\d{4}(?!\d)"), False, None),
    ("phone_intl", re.compile(r"\+\d{1,3}[ -]?\(?\d{1,4}\)?[ -]?\d{3,4}[ -]?\d{4}(?!\d)"), False, None),
    ("us_ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), False, None),
    ("kr_passport", re.compile(r"\b[MSRODG]\d{8}\b"), False, None),
    ("bank_account", re.compile(r"(?:은행|계좌|account)[^\n\d]{0,20}\d[\d-]{9,}\d"), False, None),
]

QUESTIONS = {
    "kind": {"type": "choice", "instructions": "What is the most sensitive kind of data present in the text?", "criteria": {
        "none": "no personal or secret data; code, schemas, placeholders, statistics or general text",
        "contact": "a person's name, phone, email or address",
        "government_id": "national ID / resident registration number, passport, SSN",
        "financial": "card number or bank account",
        "health": "medical or health information about a person",
        "credential": "passwords, API keys or access tokens"}},
    "about_person": {"type": "noul", "instructions": "Does this text contain personal information about a specific real individual, such as a name together with contact details, a national ID or passport number, a card or bank account number, a home address, or health information?"},
    "real_values": {"type": "noul", "instructions": "Does the text include actual values of personally identifiable information (not just field names, schemas, placeholders, or statistics)?"},
}


def mask(value):
    v = value.strip()
    keep = max(1, min(4, len(v) // 4))
    return v[:keep] + "*" * max(3, len(v) - keep * 2) + v[-keep:] if len(v) > 4 else "****"


def scan_patterns(text):
    hits = []
    for name, rx, strong, ok in PATTERNS:
        for m in rx.finditer(text):
            if ok and not ok(m):
                continue
            hits.append({"source": "regex", "type": name, "strong": strong, "sample": mask(m.group(0)), "pos": m.start()})
            break  # one sample per type is enough
    return hits


def chunks(text):
    """[(offset, part)], truncated. Long texts are sampled evenly (first and last chunk always kept)."""
    step = CHUNK_CHARS - CHUNK_OVERLAP
    offsets = list(range(0, max(len(text), 1), step))
    if len(offsets) > MAX_CHUNKS:
        picks = sorted({round(i * (len(offsets) - 1) / (MAX_CHUNKS - 1)) for i in range(MAX_CHUNKS)})
        return [(offsets[i], text[offsets[i]:offsets[i] + CHUNK_CHARS]) for i in picks], True
    return [(o, text[o:o + CHUNK_CHARS]) for o in offsets], False


def health(url=None, timeout=5):
    return json.load(urllib.request.urlopen((url or DECIDER_URL).rstrip("/") + "/health", timeout=timeout))


def ask_decider(state, url=None, timeout=20):
    body = json.dumps({"state": state, "questions": QUESTIONS}).encode()
    req = urllib.request.Request((url or DECIDER_URL).rstrip("/") + "/v1/systemone", body, {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))["answers"]


def judge_chunk(a, weak_hit):
    probs = a["kind"]["probabilities"]
    kind = max((k for k in probs if k != "none"), key=probs.get)
    # Mass on any sensitive category, not confidence in one: "health 0.80 / contact 0.17" is clearly sensitive.
    p_sensitive = 1 - probs.get("none", 0)
    p = max(a["about_person"]["noul"], a["real_values"]["noul"])
    sensitive = p_sensitive >= CAT_CONF
    finding = {"source": "decider", "type": kind, "kind_confidence": round(p_sensitive, 3), "p_pii": round(p, 3)}
    if kind == "credential" and probs["credential"] >= CAT_CONF:
        return "block", finding
    if sensitive and p >= BLOCK_P:
        return "block", finding
    if sensitive and weak_hit and p >= PATTERN_P:
        return "block", finding
    if sensitive and p >= ASK_P:
        return "ask", finding
    return "allow", finding


def check(text, decider_url=None):
    """Return {"decision": allow|ask|block, "reasons": [...], "findings": [...], ...} for one text."""
    t0 = time.time()
    text = text or ""
    hits = scan_patterns(text)
    result = {"decision": "allow", "findings": [h for h in hits], "chunks_scanned": 0, "truncated": False}
    strong = [h for h in hits if h["strong"]]
    if strong:
        result["decision"] = "block"
    elif len(text.strip()) >= 8:
        parts, result["truncated"] = chunks(text)
        for i, (lo, part) in enumerate(parts):
            weak = any(lo <= h["pos"] < lo + len(part) for h in hits)
            decision, finding = judge_chunk(ask_decider(part, decider_url), weak)
            result["chunks_scanned"] += 1
            if decision != "allow":
                finding["chunk"] = i
                result["findings"].append(finding)
            if SEVERITY[decision] > SEVERITY[result["decision"]]:
                result["decision"] = decision
            if decision == "block":
                break
    for f in result["findings"]:
        f.pop("pos", None)
    result["reasons"] = [describe(f) for f in result["findings"] if f["source"] == "decider" or f.get("strong") or result["decision"] != "allow"]
    result["latency_ms"] = round((time.time() - t0) * 1000, 1)
    return result


LABELS = {
    "kr_resident_id": "주민등록번호", "card_number": "카드번호", "aws_access_key_id": "AWS Access Key", "aws_secret_key": "AWS Secret Key",
    "private_key": "개인 키", "email": "이메일", "kr_mobile": "휴대폰 번호", "phone_intl": "전화번호", "us_ssn": "SSN",
    "kr_passport": "여권번호", "bank_account": "계좌번호", "contact": "개인 연락처/신원 정보", "government_id": "신분증 번호",
    "financial": "금융 정보", "health": "건강/의료 정보", "credential": "비밀번호/인증 정보",
}


def describe(f):
    label = LABELS.get(f["type"], f["type"])
    if f["source"] == "regex":
        return f"{label} 패턴 감지 ({f['sample']})"
    return f"{label} 판단 (decider: 민감 유형 확률 {f['kind_confidence']}, 실제 PII 확률 {f['p_pii']})"


def check_many(items, decider_url=None):
    """items: [{"source": str, "text": str}] -> overall decision plus per-item results."""
    results, overall = [], "allow"
    for it in items:
        r = check(it.get("text", ""), decider_url)
        r["source"] = it.get("source", "")
        results.append(r)
        if SEVERITY[r["decision"]] > SEVERITY[overall]:
            overall = r["decision"]
        if overall == "block":
            break
    return {"decision": overall, "results": results}
