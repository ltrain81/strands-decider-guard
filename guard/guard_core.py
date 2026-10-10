"""PII / secret guard: fast regex rules + strands-decider judgement, driven by an editable policy.

Stdlib only. Shared by the AWS Lambda (lambda_handler.py), the admin API and the hook's local
mode, so the same engine runs everywhere. Never returns or logs raw matched values: findings
carry masked samples only.

The policy (see DEFAULT_POLICY) is what admins edit in the console: an action per information
type, a sensitivity preset, custom rules written as plain-language questions, and allowlists.
"""
import copy
import json
import os
import re
import time
import urllib.request

DECIDER_URL = os.environ.get("DECIDER_URL", "http://127.0.0.1:8000")
CHUNK_CHARS = int(os.environ.get("GUARD_CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = 150
MAX_CHUNKS = int(os.environ.get("GUARD_MAX_CHUNKS", "16"))

SEVERITY = {"allow": 0, "ask": 1, "block": 2}
ACTIONS = tuple(SEVERITY)

# Information types admins can control. "kinds" are the decider's categories, "patterns" the regex types.
CATEGORIES = [
    {"id": "resident_id", "label": "주민·외국인등록번호", "desc": "주민등록번호, 외국인등록번호 형식 (예: 900101-1******). 모델 판단은 '신분증 번호' 설정을 따릅니다", "kinds": [], "patterns": ["kr_resident_id"]},
    {"id": "gov_id", "label": "신분증 번호", "desc": "여권, 운전면허, 미국 SSN 등", "kinds": ["government_id"], "patterns": ["kr_passport", "us_ssn"]},
    {"id": "financial", "label": "카드·계좌번호", "desc": "신용/체크카드 번호, 은행 계좌번호", "kinds": ["financial"], "patterns": ["card_number", "bank_account"]},
    {"id": "contact", "label": "개인 연락처·신원", "desc": "특정인의 이름과 전화번호, 이메일, 주소 등", "kinds": ["contact"], "patterns": ["email", "kr_mobile", "phone_intl"]},
    {"id": "health", "label": "건강·의료 정보", "desc": "특정인의 진단, 치료, 처방, 병력 (정규식으로는 못 잡는 문맥 판단)", "kinds": ["health"], "patterns": []},
    {"id": "credential", "label": "비밀번호·API 키", "desc": "비밀번호, 액세스 키, 토큰, 개인 키", "kinds": ["credential"], "patterns": ["aws_access_key_id", "aws_secret_key", "private_key"]},
]
CATEGORY_OF_KIND = {k: c["id"] for c in CATEGORIES for k in c["kinds"]}
CATEGORY_OF_PATTERN = {p: c["id"] for c in CATEGORIES for p in c["patterns"]}

# Thresholds per sensitivity preset. strict catches more and asks more often; lenient blocks only clear cases.
PRESETS = {
    "lenient":  {"cat": 0.85, "named": 0.65, "block": 0.85, "ask": 0.70, "pattern": 0.45, "rule": 0.70},
    "balanced": {"cat": 0.80, "named": 0.50, "block": 0.75, "ask": 0.50, "pattern": 0.30, "rule": 0.50},
    "strict":   {"cat": 0.70, "named": 0.35, "block": 0.60, "ask": 0.35, "pattern": 0.20, "rule": 0.35},
}
SENSITIVITY_LABELS = {"lenient": "관대", "balanced": "보통", "strict": "엄격"}

DEFAULT_POLICY = {
    "schema": 1,
    "sensitivity": "balanced",
    "categories": {c["id"]: "block" for c in CATEGORIES},
    "custom_rules": [],   # [{"id", "name", "question", "action", "sensitivity", "enabled"}]
    "allow": {"email_domains": [], "terms": []},
    "message": "",
}
LIMITS = {"rules": 20, "question": 300, "name": 60, "allow_items": 100, "allow_item": 100, "message": 500}


def normalize_policy(p):
    """Validate a policy and fill in defaults. Raises ValueError with a readable message."""
    p = copy.deepcopy(p or {})
    out = copy.deepcopy(DEFAULT_POLICY)
    sens = p.get("sensitivity", out["sensitivity"])
    if sens not in PRESETS:
        raise ValueError(f"알 수 없는 민감도: {sens}")
    out["sensitivity"] = sens
    for cid, action in (p.get("categories") or {}).items():
        if cid not in out["categories"]:
            raise ValueError(f"알 수 없는 정보 유형: {cid}")
        if action not in ACTIONS:
            raise ValueError(f"{cid}: 동작은 block/ask/allow 중 하나여야 합니다")
        out["categories"][cid] = action
    rules = p.get("custom_rules") or []
    if len(rules) > LIMITS["rules"]:
        raise ValueError(f"사용자 규칙은 최대 {LIMITS['rules']}개입니다")
    seen = set()
    for i, r in enumerate(rules):
        q = str(r.get("question", "")).strip()
        if not q:
            raise ValueError(f"규칙 {i + 1}: 질문이 비어 있습니다")
        if len(q) > LIMITS["question"]:
            raise ValueError(f"규칙 {i + 1}: 질문은 {LIMITS['question']}자 이내로 써 주세요")
        rid = re.sub(r"[^a-zA-Z0-9_-]", "", str(r.get("id") or f"r{i + 1}"))[:32] or f"r{i + 1}"
        while rid in seen:
            rid += "x"
        seen.add(rid)
        action = r.get("action", "block")
        rs = r.get("sensitivity", "balanced")
        if action not in ACTIONS or rs not in PRESETS:
            raise ValueError(f"규칙 {i + 1}: 동작 또는 민감도 값이 잘못되었습니다")
        out["custom_rules"].append({"id": rid, "name": str(r.get("name") or q)[:LIMITS["name"]], "question": q,
                                    "action": action, "sensitivity": rs, "enabled": bool(r.get("enabled", True))})
    allow = p.get("allow") or {}
    for key in ("email_domains", "terms"):
        vals = [str(v).strip() for v in allow.get(key, []) if str(v).strip()]
        if len(vals) > LIMITS["allow_items"] or any(len(v) > LIMITS["allow_item"] for v in vals):
            raise ValueError("허용 목록 항목이 너무 많거나 깁니다")
        out["allow"][key] = [v.lstrip("@").lower() for v in vals] if key == "email_domains" else vals
    out["message"] = str(p.get("message") or "")[:LIMITS["message"]]
    for k in ("updated_at", "updated_by"):
        if p.get(k):
            out[k] = str(p[k])[:100]
    return out


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


# (name, regex, strong, validator). Strong hits decide on their own; weak hits need the model to agree.
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
EMAIL = PATTERNS[5][1]

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
    "named_person": {"type": "noul", "instructions": "Does the text name or identify a specific individual person (for example by their real name)?"},
}


def mask(value):
    v = value.strip()
    keep = max(1, min(4, len(v) // 4))
    return v[:keep] + "*" * max(3, len(v) - keep * 2) + v[-keep:] if len(v) > 4 else "****"


def apply_allowlist(text, policy):
    """Blank out allowlisted terms and emails of allowed domains so neither regex nor the model sees them."""
    for term in policy["allow"]["terms"]:
        text = re.sub(re.escape(term), "[허용됨]", text, flags=re.IGNORECASE)
    domains = policy["allow"]["email_domains"]
    if domains:
        def repl(m):
            d = m.group(0).rsplit("@", 1)[1].lower()
            return "[허용된 이메일]" if any(d == x or d.endswith("." + x) for x in domains) else m.group(0)
        text = EMAIL.sub(repl, text)
    return text


def scan_patterns(text, policy):
    hits = []
    for name, rx, strong, ok in PATTERNS:
        action = policy["categories"][CATEGORY_OF_PATTERN[name]]
        if action == "allow":
            continue
        for m in rx.finditer(text):
            if ok and not ok(m):
                continue
            hits.append({"source": "regex", "type": name, "category": CATEGORY_OF_PATTERN[name], "strong": strong,
                         "action": action, "sample": mask(m.group(0)), "pos": m.start()})
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


def ask_decider(state, url=None, timeout=20, questions=None):
    body = json.dumps({"state": state, "questions": questions or QUESTIONS}).encode()
    req = urllib.request.Request((url or DECIDER_URL).rstrip("/") + "/v1/systemone", body, {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))["answers"]


def _cap(decision, action):
    return decision if SEVERITY[decision] <= SEVERITY[action] else action


def judge_chunk(a, weak_hit, policy):
    """PII judgement for one chunk -> (decision, finding or None)."""
    t = PRESETS[policy["sensitivity"]]
    probs = a["kind"]["probabilities"]
    enabled = [k for k in probs if k != "none" and policy["categories"][CATEGORY_OF_KIND[k]] != "allow"]
    if not enabled:
        return "allow", None
    kind = max(enabled, key=probs.get)
    action = policy["categories"][CATEGORY_OF_KIND[kind]]
    # Mass on any enabled sensitive category, not confidence in one: "health 0.80 / contact 0.17" is clearly sensitive.
    p_sensitive = sum(probs[k] for k in enabled)
    p = max(a["about_person"]["noul"], a["real_values"]["noul"])
    named = a["named_person"]["noul"]
    finding = {"source": "decider", "type": kind, "category": CATEGORY_OF_KIND[kind], "kind_confidence": round(p_sensitive, 3),
               "p_pii": round(p, 3), "p_named": round(named, 3)}
    if kind == "credential" and probs["credential"] >= t["cat"]:
        decision = "block"
    elif p_sensitive < t["cat"]:          # public figures, code, statistics: no sensitive category
        decision = "allow"
    elif named >= t["named"]:             # sensitive data about an identified person
        decision = "block"
    elif weak_hit and p >= t["pattern"]:  # a phone/email/... pattern and the model agrees
        decision = "block"
    elif p >= t["block"]:
        decision = "block"
    elif p >= t["ask"]:                   # e.g. SQL selecting name/email columns
        decision = "ask"
    else:
        decision = "allow"
    return _cap(decision, action), finding


def _questions(policy, need_pii):
    qs = dict(QUESTIONS) if need_pii else {}
    for r in policy["custom_rules"]:
        if r["enabled"] and r["action"] != "allow":
            qs[f"rule_{r['id']}"] = {"type": "noul", "instructions": r["question"]}
    return qs


def check(text, decider_url=None, policy=None):
    """Return {"decision": allow|ask|block, "reasons": [...], "findings": [...], ...} for one text."""
    t0 = time.time()
    policy = normalize_policy(policy)
    text = apply_allowlist(text or "", policy)
    hits = scan_patterns(text, policy)
    result = {"decision": "allow", "findings": list(hits), "chunks_scanned": 0, "truncated": False}
    for h in hits:
        if h["strong"] and SEVERITY[h["action"]] > SEVERITY[result["decision"]]:
            result["decision"] = h["action"]
    need_pii = any(policy["categories"][CATEGORY_OF_KIND[k]] != "allow" for k in CATEGORY_OF_KIND)
    questions = _questions(policy, need_pii)
    rules = {f"rule_{r['id']}": r for r in policy["custom_rules"]}
    if result["decision"] != "block" and questions and len(text.strip()) >= 8:
        parts, result["truncated"] = chunks(text)
        for i, (lo, part) in enumerate(parts):
            answers = ask_decider(part, decider_url, questions=questions)
            result["chunks_scanned"] += 1
            verdicts = []
            if need_pii:
                weak = any(lo <= h["pos"] < lo + len(part) for h in hits if not h["strong"])
                verdicts.append(judge_chunk(answers, weak, policy))
            for key, r in rules.items():
                if key in answers:
                    p = answers[key]["noul"]
                    hit = p >= PRESETS[r["sensitivity"]]["rule"]
                    verdicts.append((r["action"] if hit else "allow",
                                     {"source": "rule", "type": r["id"], "name": r["name"], "p": round(p, 3)}))
            for decision, finding in verdicts:
                if decision != "allow" and finding:
                    finding["chunk"] = i
                    result["findings"].append(finding)
                if SEVERITY[decision] > SEVERITY[result["decision"]]:
                    result["decision"] = decision
            if result["decision"] == "block":
                break
    for f in result["findings"]:
        f.pop("pos", None)
    result["reasons"] = [describe(f) for f in result["findings"]] if result["decision"] != "allow" else []
    result["latency_ms"] = round((time.time() - t0) * 1000, 1)
    return result


LABELS = {
    "kr_resident_id": "주민등록번호", "card_number": "카드번호", "aws_access_key_id": "AWS Access Key", "aws_secret_key": "AWS Secret Key",
    "private_key": "개인 키", "email": "이메일", "kr_mobile": "휴대폰 번호", "phone_intl": "전화번호", "us_ssn": "SSN",
    "kr_passport": "여권번호", "bank_account": "계좌번호", "contact": "개인 연락처/신원 정보", "government_id": "신분증 번호",
    "financial": "금융 정보", "health": "건강/의료 정보", "credential": "비밀번호/인증 정보",
}


def describe(f):
    if f["source"] == "rule":
        return f"사용자 규칙 '{f['name']}' 에 해당 (확률 {f['p']})"
    label = LABELS.get(f["type"], f["type"])
    if f["source"] == "regex":
        return f"{label} 패턴 감지 ({f['sample']})"
    return f"{label} 판단 (decider: 민감 유형 확률 {f['kind_confidence']}, 특정인 확률 {f['p_named']}, 실제 PII 확률 {f['p_pii']})"


def check_many(items, decider_url=None, policy=None):
    """items: [{"source": str, "text": str}] -> overall decision plus per-item results."""
    policy = normalize_policy(policy)
    results, overall = [], "allow"
    for it in items:
        r = check(it.get("text", ""), decider_url, policy)
        r["source"] = it.get("source", "")
        results.append(r)
        if SEVERITY[r["decision"]] > SEVERITY[overall]:
            overall = r["decision"]
        if overall == "block":
            break
    return {"decision": overall, "results": results, "message": policy["message"]}
