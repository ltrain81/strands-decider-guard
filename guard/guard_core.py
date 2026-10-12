"""PII / secret guard: fast regex rules + strands-decider judgement, driven by an editable policy.

Stdlib only. Shared by the AWS Lambda (lambda_handler.py), the admin API and the hook's local
mode, so the same engine runs everywhere. Never returns or logs raw matched values: findings
carry masked samples only.

The policy (see DEFAULT_POLICY) is what admins edit in the console: an action per information
type, a sensitivity preset, custom rules written as plain-language questions, and allowlists.
"""
import copy
import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

DECIDER_URL = os.environ.get("DECIDER_URL", "http://127.0.0.1:8000")
CHUNK_CHARS = int(os.environ.get("GUARD_CHUNK_CHARS", "1500"))
CHUNK_OVERLAP = 150
MAX_CHUNKS = int(os.environ.get("GUARD_MAX_CHUNKS", "16"))

SEVERITY = {"allow": 0, "ask": 1, "block": 2}
ACTIONS = tuple(SEVERITY)

# Information types admins can control. "kinds" are the decider's categories, "patterns" the regex types.
LANGS = ("en", "ko")
CATEGORIES = [
    {"id": "resident_id", "kinds": [], "patterns": ["kr_resident_id"],
     "label": {"en": "Resident registration number", "ko": "주민·외국인등록번호"},
     "desc": {"en": "Korean resident / alien registration number format (e.g. 900101-1******). The model's ID judgement follows 'Government ID'.",
              "ko": "주민등록번호, 외국인등록번호 형식 (예: 900101-1******). 모델 판단은 '신분증 번호' 설정을 따릅니다"}},
    {"id": "gov_id", "kinds": ["government_id"], "patterns": ["kr_passport", "us_ssn"],
     "label": {"en": "Government ID", "ko": "신분증 번호"},
     "desc": {"en": "Passport, driver's license, US SSN and similar", "ko": "여권, 운전면허, 미국 SSN 등"}},
    {"id": "financial", "kinds": ["financial"], "patterns": ["card_number", "bank_account"],
     "label": {"en": "Card / bank account", "ko": "카드·계좌번호"},
     "desc": {"en": "Credit/debit card numbers, bank account numbers", "ko": "신용/체크카드 번호, 은행 계좌번호"}},
    {"id": "contact", "kinds": ["contact"], "patterns": ["email", "kr_mobile", "phone_intl"],
     "label": {"en": "Personal contact / identity", "ko": "개인 연락처·신원"},
     "desc": {"en": "A specific person's name with phone, email or address", "ko": "특정인의 이름과 전화번호, 이메일, 주소 등"}},
    {"id": "health", "kinds": ["health"], "patterns": [],
     "label": {"en": "Health / medical", "ko": "건강·의료 정보"},
     "desc": {"en": "A specific person's diagnosis, treatment, prescriptions or history (context judgement regex cannot do)",
              "ko": "특정인의 진단, 치료, 처방, 병력 (정규식으로는 못 잡는 문맥 판단)"}},
    {"id": "private_life", "kinds": ["private_life"], "patterns": [],
     "label": {"en": "HR / legal / private life", "ko": "인사·법률·사생활"},
     "desc": {"en": "A specific person's HR or disciplinary matter, legal case, criminal record, immigration status, beliefs, union membership, sexual orientation or family situation",
              "ko": "특정인의 인사·징계, 소송, 범죄 경력, 체류 자격, 종교·정치 성향, 노조 가입, 성적 지향, 가족 사정"}},
    {"id": "credential", "kinds": ["credential"], "patterns": ["aws_access_key_id", "aws_secret_key", "private_key"],
     "label": {"en": "Passwords / API keys", "ko": "비밀번호·API 키"},
     "desc": {"en": "Passwords, access keys, tokens, private keys", "ko": "비밀번호, 액세스 키, 토큰, 개인 키"}},
]
CATEGORY_OF_KIND = {k: c["id"] for c in CATEGORIES for k in c["kinds"]}
CATEGORY_OF_PATTERN = {p: c["id"] for c in CATEGORIES for p in c["patterns"]}

# Thresholds per sensitivity preset. strict catches more and asks more often; lenient blocks only clear cases.
PRESETS = {  # chosen by bench/tune.py on the tune half, reported on the holdout half (bench/TUNING.md)
    "lenient": {"cat": 0.6, "named": 0.5, "block": 0.85, "ask": 0.5, "pattern": 0.2, "weak_ps": None, "named_cat": None, "cred_real": 0.3, "rule": 0.7},
    "balanced": {"cat": 0.6, "named": 0.35, "block": 0.85, "ask": 0.5, "pattern": 0.2, "weak_ps": 0.3, "named_cat": None, "cred_real": 0.3, "rule": 0.5},
    "strict": {"cat": 0.9, "named": 0.35, "block": 0.6, "ask": 0.5, "pattern": 0.2, "weak_ps": 0.3, "named_cat": 0.4, "cred_real": 0.0, "rule": 0.35},
}
SENSITIVITY_LABELS = {"en": {"lenient": "Lenient", "balanced": "Balanced", "strict": "Strict"},
                      "ko": {"lenient": "관대", "balanced": "보통", "strict": "엄격"}}

# User-facing strings: admin validation errors and verdict reasons. Findings themselves stay structured.
TEXT = {
    "en": {
        "bad_sensitivity": "Unknown sensitivity: {v}", "bad_category": "Unknown information type: {v}",
        "bad_action": "{v}: action must be block, ask or allow", "too_many_rules": "At most {n} custom rules",
        "empty_question": "Rule {i}: the question is empty", "long_question": "Rule {i}: keep the question under {n} characters",
        "bad_rule": "Rule {i}: invalid action or sensitivity", "bad_allow": "Too many or too long allowlist entries",
        "bad_mode": "{k}: unknown value {v}",
        "basis_pattern": "decided by format check (pattern)", "basis_model_pattern": "decided by the model, prompted by a pattern",
        "basis_model": "decided by the model alone", "basis_rule": "decided by a company rule (model)",
        "basis_degraded": "decided by patterns only (model unavailable)",
        "rule_hit": "custom rule '{name}' matched (p={p})", "pattern": "{label} pattern found ({sample})",
        "model": "{label} (decider: sensitive {s}, specific person {n}, real PII {r})",
        "degraded": "model unavailable: checked with patterns only",
    },
    "ko": {
        "bad_sensitivity": "알 수 없는 민감도: {v}", "bad_category": "알 수 없는 정보 유형: {v}",
        "bad_action": "{v}: 동작은 block/ask/allow 중 하나여야 합니다", "too_many_rules": "사용자 규칙은 최대 {n}개입니다",
        "empty_question": "규칙 {i}: 질문이 비어 있습니다", "long_question": "규칙 {i}: 질문은 {n}자 이내로 써 주세요",
        "bad_rule": "규칙 {i}: 동작 또는 민감도 값이 잘못되었습니다", "bad_allow": "허용 목록 항목이 너무 많거나 깁니다",
        "bad_mode": "{k}: 알 수 없는 값 {v}",
        "basis_pattern": "판정 근거: 형식 검사(패턴)", "basis_model_pattern": "판정 근거: 패턴이 찾은 후보를 모델이 판단",
        "basis_model": "판정 근거: 모델 단독 판단", "basis_rule": "판정 근거: 회사 규칙(모델)",
        "basis_degraded": "판정 근거: 패턴만 (모델 사용 불가)",
        "rule_hit": "사용자 규칙 '{name}' 에 해당 (확률 {p})", "pattern": "{label} 패턴 감지 ({sample})",
        "model": "{label} 판단 (decider: 민감 유형 확률 {s}, 특정인 확률 {n}, 실제 PII 확률 {r})",
        "degraded": "모델에 연결할 수 없어 패턴으로만 검사했습니다",
    },
}


def lang_of(lang):
    return lang if lang in LANGS else "en"


def t(lang, key, **kw):
    return TEXT[lang_of(lang)][key].format(**kw)

DEFAULT_POLICY = {
    "schema": 1,
    "sensitivity": "balanced",
    "categories": {c["id"]: "block" for c in CATEGORIES},
    "custom_rules": [],   # [{"id", "name", "question", "action", "sensitivity", "enabled"}]
    "allow": {"email_domains": [], "terms": []},
    "message": "",
    "patterns": "assist",   # off: the model decides alone | strong: only checksum/format-certain patterns | assist: + weak hints
    "evidence": "off",      # off | blocked | all: keep the checked text (encrypted, expiring) for admins to review
}
PATTERN_MODES = ("off", "strong", "assist")
EVIDENCE_MODES = ("off", "blocked", "all")
LIMITS = {"rules": 20, "question": 300, "name": 60, "allow_items": 100, "allow_item": 100, "message": 500}


def normalize_policy(p, lang="en"):
    """Validate a policy and fill in defaults. Raises ValueError with a readable (localized) message."""
    p = copy.deepcopy(p or {})
    out = copy.deepcopy(DEFAULT_POLICY)
    sens = p.get("sensitivity", out["sensitivity"])
    if sens not in PRESETS:
        raise ValueError(t(lang, "bad_sensitivity", v=sens))
    out["sensitivity"] = sens
    for cid, action in (p.get("categories") or {}).items():
        if cid not in out["categories"]:
            raise ValueError(t(lang, "bad_category", v=cid))
        if action not in ACTIONS:
            raise ValueError(t(lang, "bad_action", v=cid))
        out["categories"][cid] = action
    rules = p.get("custom_rules") or []
    if len(rules) > LIMITS["rules"]:
        raise ValueError(t(lang, "too_many_rules", n=LIMITS["rules"]))
    seen = set()
    for i, r in enumerate(rules):
        q = str(r.get("question", "")).strip()
        if not q:
            raise ValueError(t(lang, "empty_question", i=i + 1))
        if len(q) > LIMITS["question"]:
            raise ValueError(t(lang, "long_question", i=i + 1, n=LIMITS["question"]))
        rid = re.sub(r"[^a-zA-Z0-9_-]", "", str(r.get("id") or f"r{i + 1}"))[:32] or f"r{i + 1}"
        while rid in seen:
            rid += "x"
        seen.add(rid)
        action = r.get("action", "block")
        rs = r.get("sensitivity", "balanced")
        if action not in ACTIONS or rs not in PRESETS:
            raise ValueError(t(lang, "bad_rule", i=i + 1))
        out["custom_rules"].append({"id": rid, "name": str(r.get("name") or q)[:LIMITS["name"]], "question": q,
                                    "action": action, "sensitivity": rs, "enabled": bool(r.get("enabled", True))})
    allow = p.get("allow") or {}
    for key in ("email_domains", "terms"):
        vals = [str(v).strip() for v in allow.get(key, []) if str(v).strip()]
        if len(vals) > LIMITS["allow_items"] or any(len(v) > LIMITS["allow_item"] for v in vals):
            raise ValueError(t(lang, "bad_allow"))
        out["allow"][key] = [v.lstrip("@").lower() for v in vals] if key == "email_domains" else vals
    out["message"] = str(p.get("message") or "")[:LIMITS["message"]]
    for key, allowed in (("patterns", PATTERN_MODES), ("evidence", EVIDENCE_MODES)):
        v = p.get(key, out[key])
        if v not in allowed:
            raise ValueError(t(lang, "bad_mode", k=key, v=v))
        out[key] = v
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


# Published test card numbers (payment-provider docs) appear in code all the time; stored as hash prefixes.
TEST_CARDS = {"19ff47cc8024c133", "2f725bbd1f405a1e", "304945e91de3deff", "3a134ef77d4e2e4c", "477bba133c182267", "53a8fc816e63b7a5", "576c15a8072461c2", "68594afe9c9cda52", "9bbef19476623ca5", "eceedffc6daaad3b"}


def _card(m):
    d = re.sub(r"\D", "", m.group(0))
    if hashlib.sha256(d.encode()).hexdigest()[:16] in TEST_CARDS:
        return False
    return 13 <= len(d) <= 19 and d[0] in "2345" and _luhn(d)


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
        "none": "no personal or secret data: code, schemas, column names, placeholders, templates, policies, statistics or general text",
        "contact": "a specific person's name together with a phone number, email, home address, date of birth or account/customer ID",
        "government_id": "a national ID or resident registration number, passport, driver's license, SSN or tax ID",
        "financial": "a card number, bank account or IBAN, or a specific person's transactions or debts",
        "health": "medical or health information about a specific person",
        "private_life": "a specific person's HR or disciplinary matter, legal case, criminal record, immigration status, religion, political views, union membership, sexual orientation or family situation",
        "credential": "passwords, API keys, access tokens or private keys"}},
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
        text = re.sub(re.escape(term), "[allowed]", text, flags=re.IGNORECASE)
    domains = policy["allow"]["email_domains"]
    if domains:
        def repl(m):
            d = m.group(0).rsplit("@", 1)[1].lower()
            return "[allowed email]" if any(d == x or d.endswith("." + x) for x in domains) else m.group(0)
        text = EMAIL.sub(repl, text)
    return text


def scan_patterns(text, policy):
    mode = policy.get("patterns", "assist")
    hits = []
    for name, rx, strong, ok in PATTERNS:
        if mode == "off" or (mode == "strong" and not strong):
            continue
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


class DeciderUnavailable(Exception):
    """The model server cannot be reached (host stopped, network); callers fall back to regex-only checks."""


_down_until = 0.0  # after a connection failure, skip the model for a while instead of waiting on every call
_up_until = 0.0    # after a success, skip the quick reachability probe for a while
DOWN_SECONDS, UP_SECONDS, CONNECT_TIMEOUT = 30, 60, 1.5


def _reachable(url):
    """Fast TCP check so a stopped host costs ~1.5 s once, not the full request timeout on every call."""
    global _up_until
    if time.time() < _up_until:
        return True
    from urllib.parse import urlsplit
    u = urlsplit(url)
    try:
        socket.create_connection((u.hostname, u.port or 80), timeout=CONNECT_TIMEOUT).close()
    except OSError:
        return False
    _up_until = time.time() + UP_SECONDS
    return True


def ask_decider(state, url=None, timeout=20, questions=None):
    """One model call. Transient server errors (seen under concurrent load) are retried; an unreachable server
    raises DeciderUnavailable right away and is not retried for DOWN_SECONDS."""
    global _down_until
    if time.time() < _down_until:
        raise DeciderUnavailable("model server marked down")
    base = (url or DECIDER_URL).rstrip("/")
    if not _reachable(base):
        _down_until = time.time() + DOWN_SECONDS
        raise DeciderUnavailable(f"{base} is not reachable")
    body = json.dumps({"state": state, "questions": questions or QUESTIONS}).encode()
    req = urllib.request.Request(base + "/v1/systemone", body, {"content-type": "application/json"})
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))["answers"]
        except urllib.error.HTTPError as e:
            if e.code not in (422, 429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(0.2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _down_until = time.time() + DOWN_SECONDS
            raise DeciderUnavailable(str(e)) from e


def _cap(decision, action):
    return decision if SEVERITY[decision] <= SEVERITY[action] else action


def judge_chunk(a, weak_hit, policy):
    """PII judgement for one chunk -> (decision, finding or None). Mirrors bench/tune.py's decide()."""
    t = PRESETS[policy["sensitivity"]]
    probs = a["kind"]["probabilities"]
    enabled = [k for k in probs if k != "none" and k in CATEGORY_OF_KIND and policy["categories"][CATEGORY_OF_KIND[k]] != "allow"]
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
        # placeholders such as ${DB_PASSWORD} look like credentials but carry no real value
        finding["path"] = "model"
        return (_cap("block", action), finding) if p >= t["cred_real"] else ("allow", None)
    path = "model"
    if t["weak_ps"] is not None and weak_hit and p_sensitive >= t["weak_ps"]:
        decision, path = "block", "model_pattern"   # an email/phone/... pattern the model sees as at least somewhat sensitive
    elif t["named_cat"] is not None and named >= t["named"] and p_sensitive >= t["named_cat"]:
        decision = "block"                # a named person in a moderately sensitive context
    elif p_sensitive < t["cat"]:          # public figures, code, statistics: no sensitive category
        decision = "allow"
    elif named >= t["named"] or p >= t["block"]:
        decision = "block"
    elif weak_hit and p >= t["pattern"]:
        decision, path = "block", "model_pattern"
    elif p >= t["ask"]:                   # e.g. SQL selecting name/email columns
        decision = "ask"
    else:
        decision = "allow"
    finding["path"] = path
    return _cap(decision, action), finding


def _questions(policy, need_pii):
    qs = dict(QUESTIONS) if need_pii else {}
    for r in policy["custom_rules"]:
        if r["enabled"] and r["action"] != "allow":
            qs[f"rule_{r['id']}"] = {"type": "noul", "instructions": r["question"]}
    return qs


def check(text, decider_url=None, policy=None, lang="en", degrade=True):
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
            try:
                answers = ask_decider(part, decider_url, questions=questions)
            except DeciderUnavailable:
                if not degrade:
                    raise
                # Regex-only fallback: strong patterns already decided above; weak ones (email, phone, ...) ask.
                result["degraded"] = True
                result["findings"].append({"source": "degraded", "type": "degraded"})
                if any(not h["strong"] for h in hits) and SEVERITY[result["decision"]] < SEVERITY["ask"]:
                    result["decision"] = "ask"
                break
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
    result["basis"] = basis_of(result)
    result["basis_label"] = t(lang, "basis_" + result["basis"]) if result["basis"] else ""
    result["reasons"] = [describe(f, lang) for f in result["findings"]] if result["decision"] != "allow" else []
    result["latency_ms"] = round((time.time() - t0) * 1000, 1)
    return result


PATTERN_LABELS = {
    "en": {"kr_resident_id": "Resident registration number", "card_number": "Card number", "aws_access_key_id": "AWS access key",
           "aws_secret_key": "AWS secret key", "private_key": "Private key", "email": "Email", "kr_mobile": "Mobile number",
           "phone_intl": "Phone number", "us_ssn": "SSN", "kr_passport": "Passport number", "bank_account": "Bank account",
           "contact": "Personal contact / identity", "government_id": "Government ID", "financial": "Financial data",
           "health": "Health / medical data", "private_life": "HR / legal / private life", "credential": "Password / credential"},
    "ko": {"kr_resident_id": "주민등록번호", "card_number": "카드번호", "aws_access_key_id": "AWS Access Key", "aws_secret_key": "AWS Secret Key",
           "private_key": "개인 키", "email": "이메일", "kr_mobile": "휴대폰 번호", "phone_intl": "전화번호", "us_ssn": "SSN",
           "kr_passport": "여권번호", "bank_account": "계좌번호", "contact": "개인 연락처/신원 정보", "government_id": "신분증 번호",
           "financial": "금융 정보", "health": "건강/의료 정보", "private_life": "인사·법률·사생활 정보", "credential": "비밀번호/인증 정보"},
}


def basis_of(result):
    """Which part of the guard made a non-allow decision: pattern | model_pattern | model | rule | degraded (None if allowed)."""
    if result["decision"] == "allow":
        return None
    sev = SEVERITY[result["decision"]]
    fs = result["findings"]
    if any(f["source"] == "regex" and f.get("strong") and SEVERITY[f.get("action", "block")] >= sev for f in fs):
        return "pattern"
    for f in fs:
        if f["source"] == "decider":
            return f.get("path", "model")
        if f["source"] == "rule":
            return "rule"
    return "degraded" if result.get("degraded") else "pattern"


def describe(f, lang="en"):
    if f["source"] == "degraded":
        return t(lang, "degraded")
    if f["source"] == "rule":
        return t(lang, "rule_hit", name=f["name"], p=f["p"])
    label = PATTERN_LABELS[lang_of(lang)].get(f["type"], f["type"])
    if f["source"] == "regex":
        return t(lang, "pattern", label=label, sample=f["sample"])
    return t(lang, "model", label=label, s=f["kind_confidence"], n=f["p_named"], r=f["p_pii"])


def check_many(items, decider_url=None, policy=None, lang="en", degrade=True):
    """items: [{"source": str, "text": str}] -> overall decision plus per-item results."""
    policy = normalize_policy(policy)
    results, overall = [], "allow"
    for it in items:
        r = check(it.get("text", ""), decider_url, policy, lang, degrade)
        r["source"] = it.get("source", "")
        results.append(r)
        if SEVERITY[r["decision"]] > SEVERITY[overall]:
            overall = r["decision"]
        if overall == "block":
            break
    return {"decision": overall, "results": results, "message": policy["message"]}
