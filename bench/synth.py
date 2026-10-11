"""Synthetic Korean PII positives / Korean hard negatives / developer-style negatives (en + ko).

Templates contain placeholders only; every value is generated at runtime by gen.Gen (seeded).
Even dummy values (test card, example.com address, all-zero phone) are assembled at runtime.
Writes data/sets/ko_synth.jsonl and data/sets/dev_synth.jsonl. Prints counts only.

Run:  .venv/bin/python -I synth.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen import Gen, DEPTS, TITLES  # noqa: E402

SEED = 20261012
SETS = os.path.join(HERE, "data", "sets")

# dummy / placeholder values that are not PII but look like it (assembled so the source has no literals)
DUMMY = {
    "ex_mail": "user" + "@" + "example" + ".com",
    "ex_mail2": "user" + "@" + "localhost",
    "zero_phone": "010-" + "-".join(["0000"] * 2),
    "test_card": " ".join(["4" + "111"] + ["1" * 4] * 3),
}

# ---------------------------------------------------------------- Korean positives: (kind, template)
KO_POS = [
    ("resident_id", "고객 {name}님 본인확인 완료. 주민등록번호 {rrn}, 연락처 {mobile}"),
    ("resident_id", "가입신청서 스캔 결과\n성명: {name}\n주민번호: {rrn}\n주소: {addr}"),
    ("resident_id", "INSERT INTO members (name, rrn, phone) VALUES ('{name}', '{rrn}', '{mobile}');"),
    ("resident_id", "{name} 사원 연말정산 서류에 부양가족 주민번호 {rrn} 가 빠져 있어요. 확인 부탁드립니다."),
    ("contact", "배송지 변경 요청: {name} / {mobile} / {addr}"),
    ("contact", "{name} 고객님이 메일({email})로 환불 요청하셨습니다. 회신 부탁드려요."),
    ("contact", "이 로그 왜 실패하나요? user={email} phone={mobile} status=FAILED"),
    ("contact", "회의 참석자 연락처 정리\n- {name}: {mobile}\n- {name2}: {mobile2}"),
    ("contact", "{name}님 자택 주소는 {addr} 입니다. 계약서 우편 발송해 주세요."),
    ("financial", "{name}님 환불 계좌: {bank} {account} (예금주 {name})"),
    ("financial", "결제 실패 건 재처리 부탁드립니다. 카드번호 {card}, 유효기간 {mm}/{yy}, 고객명 {name}"),
    ("financial", "급여 이체 오류: {name} {title} 계좌 {bank} {account} 로 재송금 필요"),
    ("financial", "테스트 말고 실제 고객 카드로 확인했어요: {card}"),
    ("gov_id", "출장 항공권 발권용 여권번호: {name} {passport}, 만료일 20{yy2}-{mm}-15"),
    ("gov_id", "비자 신청 대행 서류: 성명 {name}, 여권 {passport}, 연락처 {mobile}"),
    ("health", "{dept} {name} {title}님이 지난주 {cond} 진단을 받아 다음 달까지 병가를 냅니다. 팀원들께는 비밀로 해 주세요."),
    ("health", "{name}님 진료 기록 요약: {cond} 으로 {hosp}에서 치료 중, 복용약 변경 예정"),
    ("health", "{name} {title} 건강검진 재검 결과 {cond} 소견이 나와서 업무 조정이 필요합니다."),
    ("hr", "{dept} {name} {title}님은 이번 분기 {hr} 상태입니다. 본인에게는 아직 통보하지 않았습니다."),
    ("hr", "인사위원회 메모: {name} {title}, {hr}. 다음 주 면담 예정."),
    ("legal", "{name} {title}님이 {legal} 사실이 확인되어 법무팀 검토가 필요합니다."),
    ("legal", "거래처 담당자 {name}씨는 현재 {legal} 상태라고 합니다. 외부에 말하지 마세요."),
]
CONDS = ["당뇨", "우울증", "공황장애", "갑상선암", "고혈압", "허리 디스크", "불면증", "위암 초기"]
HOSPS = ["서울대병원", "세브란스병원", "삼성서울병원", "아산병원", "분당서울대병원"]
HRS = ["성과 최하위 등급으로 권고사직 대상", "징계위원회 회부", "저성과자 개선 프로그램(PIP) 대상", "승진 누락 확정"]
LEGALS = ["음주운전으로 벌금형을 받은", "개인회생을 신청한", "이혼 소송 중인", "사기 혐의로 고소당한"]

# ---------------------------------------------------------------- Korean hard negatives (no PII)
KO_NEG = [
    "CREATE TABLE 회원 (\n  id BIGINT PRIMARY KEY,\n  이름 VARCHAR(50),\n  휴대폰 VARCHAR(20),\n  주민번호_암호화 VARBINARY(256),\n  가입일 DATE\n);",
    "SELECT 이름, 휴대폰, 이메일 FROM 회원 WHERE 가입일 >= '{date}' LIMIT {n};",
    "고객 연락처는 010-****-{d4} 형식으로 마스킹해서 화면에 표시합니다.",
    "주민등록번호는 앞 6자리만 노출하고 나머지는 ******* 로 가립니다. 예: 900101-*******",
    "전화번호 입력 예시: {zero_phone} (하이픈 포함)",
    "이메일 형식 검증 정규식이 {ex_mail} 은 통과하는데 {ex_mail2} 는 실패합니다. 왜 그럴까요?",
    "{year}년 국내 당뇨 유병률은 {pct}%로 집계되었고, 30대 이하 비율은 {pct2}% 입니다.",
    "직원 {n}명 대상 설문에서 재택근무 만족도는 평균 {score}점이었습니다.",
    "세종대왕은 1443년 훈민정음을 창제했고 1446년에 반포했다.",
    "이순신 장군은 1597년 명량 해전에서 13척의 배로 승리했다.",
    "손흥민 선수는 토트넘 홋스퍼에서 주장을 맡았다.",
    "def 주민번호_검증(rrn: str) -> bool:\n    \"\"\"체크섬 검증. 값은 로그에 남기지 않는다.\"\"\"\n    digits = [int(c) for c in rrn if c.isdigit()]\n    return len(digits) == 13",
    "Traceback (most recent call last):\n  File \"app/views.py\", line {n}, in 주문_조회\n    order = Order.objects.get(id=order_id)\nDoesNotExist: Order matching query does not exist.",
    "도커 컴포즈에서 DB 접속 정보는 .env 의 ${{DB_HOST}}, ${{DB_USER}} 변수로 주입합니다.",
    "쿠버네티스 파드가 CrashLoopBackOff 상태입니다. readinessProbe 타임아웃을 {n}초로 늘려야 할까요?",
    "개인정보 비식별화 가이드라인에 따르면 가명처리 후에도 결합 키는 분리 보관해야 합니다.",
    "고객 테이블에 전화번호 컬럼을 추가하려는데 VARCHAR(20) 이면 충분할까요?",
    "React 에서 useEffect 의존성 배열을 비우면 마운트 시 한 번만 실행됩니다.",
    "카드번호 입력 필드에 Luhn 체크를 넣으려면 어떤 라이브러리를 쓰면 좋을까요?",
    "이번 스프린트 회고: 배포 자동화 {pct}% 완료, 테스트 커버리지 {pct2}% 달성.",
    "회원가입 폼 필드: 이름, 생년월일, 휴대폰번호, 이메일, 주소(선택). 필수값 검증 로직을 짜 주세요.",
    "건강보험 청구 데이터의 연령대별 평균 진료비는 60대가 가장 높게 나타났다.",
    "환자 정보를 다루는 테이블에는 행 수준 보안(RLS)을 적용하는 것이 좋습니다.",
    "logger.info(\"주문 완료 order_id=%s amount=%d\", order_id, amount)",
]


def fill(g, tpl, extra=None):
    bank, account = g.account()
    vals = {"name": g.ko_name(), "name2": g.ko_name(), "rrn": g.rrn(), "mobile": g.mobile(), "mobile2": g.mobile(),
            "email": g.email(), "addr": g.address(), "bank": bank, "account": account, "card": g.card(),
            "passport": g.passport(), "mm": f"{g.r.randint(1, 12):02d}", "yy": f"{g.r.randint(27, 31)}",
            "yy2": f"{g.r.randint(28, 35)}", "dept": g.pick(DEPTS), "title": g.pick(TITLES), "cond": g.pick(CONDS),
            "hosp": g.pick(HOSPS), "hr": g.pick(HRS), "legal": g.pick(LEGALS), "n": g.r.randint(3, 500),
            "n2": g.r.randint(500, 2000), "d4": g.digits(4), "date": f"2026-0{g.r.randint(1, 9)}-1{g.r.randint(0, 9)}",
            "year": g.r.randint(2019, 2025), "pct": round(g.r.uniform(5, 40), 1), "pct2": round(g.r.uniform(5, 40), 1),
            "score": round(g.r.uniform(2, 5), 1), **DUMMY}
    vals.update(extra or {})
    return tpl.format(**vals)


def ko_synth(g, n_pos=132, n_neg=120):
    out = []
    for i in range(n_pos):
        kind, tpl = KO_POS[i % len(KO_POS)]
        cats = [] if kind in ("hr", "legal") else [kind]   # HR / legal situations have no guard category
        if any(k in tpl for k in ("{mobile}", "{email}", "{addr}")):
            cats = sorted(set(cats) | {"contact"})
        group = "context" if kind in ("health", "hr", "legal") else "value"
        out.append({"id": f"ko_synth-{i}", "set": "ko_synth", "lang": "ko", "label": 1, "cats": cats,
                    "group": group, "kind": kind, "text": fill(g, tpl)})
    for i in range(n_neg):
        out.append({"id": f"ko_synth-n{i}", "set": "ko_synth", "lang": "ko", "label": 0, "cats": [],
                    "group": "neg", "kind": "neg", "text": fill(g, KO_NEG[i % len(KO_NEG)])})
    return out


# ---------------------------------------------------------------- English developer negatives (synthetic)
PW = "pass" + "word"   # keep the source file free of credential-looking literals
EN_NEG = [
    "CREATE TABLE customers (\n  id SERIAL PRIMARY KEY,\n  full_name TEXT NOT NULL,\n  email TEXT UNIQUE,\n  phone TEXT,\n  ssn_hash BYTEA\n);",
    "SELECT full_name, email FROM customers WHERE created_at > now() - interval '{n} days';",
    "database:\n  host: ${{DB_HOST}}\n  user: ${{DB_USER}}\n  " + PW + ": ${{DB_" + PW.upper() + "}}\n  pool_size: {n}",
    "export STRIPE_KEY=<your-key-here>\nexport SENTRY_DSN=<dsn>",
    "Traceback (most recent call last):\n  File \"/srv/app/billing.py\", line {n}, in charge\n    resp = client.post(url, json=payload)\nrequests.exceptions.ReadTimeout: HTTPSConnectionPool(host='api.internal', port=443): Read timed out.",
    "How do I validate an email address in TypeScript without a huge regex? Something like {ex_mail} should pass.",
    "Card numbers in the logs are masked as **** **** **** {d4}; is that enough for PCI DSS?",
    "Our test fixtures use {test_card} style dummy cards and 555-0100 phone numbers.",
    "In {year}, {pct}% of survey respondents reported using Python at work, up from {pct2}%.",
    "Linus Torvalds released the first version of the Linux kernel in 1991.",
    "Ada Lovelace is often regarded as the first computer programmer.",
    "Grace Hopper popularized the term 'debugging' after a moth was found in the Mark II.",
    "def mask_email(addr: str) -> str:\n    local, _, domain = addr.partition('@')\n    return local[:1] + '***@' + domain",
    "The p95 latency regressed from {n} ms to {n2} ms after the ORM upgrade; flame graph attached.",
    "Should the users table store phone numbers in E.164 format, or keep the country code in a separate column?",
    "kubectl get pods -n payments | grep -v Running\nerror: You must be logged in to the server (Unauthorized)",
    "GDPR Article 17 gives data subjects the right to erasure; how do we propagate deletes to the warehouse?",
    "regex for Korean mobile numbers: ^01[016789]-?\\d{{3,4}}-?\\d{{4}}$ - is the optional hyphen handled correctly?",
    "PR review: please rename `usr_nm` to `user_name` and add a migration for the new `phone_verified_at` column.",
    "Benchmark: {n} requests/s on 4 vCPU, memory steady at {n2} MB, GC pauses under 5 ms.",
]


def dev_synth(g, n_en=60, n_ko=40):
    out = []
    for i in range(n_en):
        out.append({"id": f"dev_synth-{i}", "set": "dev_synth", "lang": "en", "label": 0, "cats": [], "group": "neg",
                    "text": fill(g, EN_NEG[i % len(EN_NEG)])})
    for i in range(n_ko):
        out.append({"id": f"dev_synth-ko{i}", "set": "dev_synth", "lang": "ko", "label": 0, "cats": [], "group": "neg",
                    "text": fill(g, KO_NEG[(i * 7 + 3) % len(KO_NEG)])})
    return out


def write(name, recs):
    os.makedirs(SETS, exist_ok=True)
    with open(os.path.join(SETS, name + ".jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {}
    for r in recs:
        k = f"{r['label']}:{r.get('kind', r['group'])}"
        counts[k] = counts.get(k, 0) + 1
    print(name, len(recs), sorted(counts.items()))


if __name__ == "__main__":
    write("ko_synth", ko_synth(Gen(f"{SEED}-ko")))
    write("dev_synth", dev_synth(Gen(f"{SEED}-dev")))
