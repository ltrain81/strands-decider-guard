"""Custom-rule benchmark set: 4 plain-language company rules, positives + hard negatives, English + Korean.

The internal project code name "Kestrel" is invented for this benchmark; the hard negatives use the
real open-source ASP.NET Core "Kestrel" web server (and the bird). Values are generated at runtime (seeded).
Writes data/sets/rules.jsonl. Prints counts only.

Run:  .venv/bin/python -I rules.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen import Gen  # noqa: E402

SEED = 20261012
SETS = os.path.join(HERE, "data", "sets")
N_PER_SIDE = 30  # per rule: 30 positives + 30 hard negatives

RULES = [
    {"id": "kestrel", "name": "Project Kestrel (unreleased)",
     "question": "Does the text reveal unreleased plans, schedules, budgets, features or partners of the company's "
                 "internal project code-named Kestrel?"},
    {"id": "comp", "name": "Employee compensation / reviews",
     "question": "Does the text disclose a specific employee's compensation (salary, bonus, equity) or the result of "
                 "their performance review?"},
    {"id": "contract", "name": "Customer contract terms",
     "question": "Does the text reveal the amount, pricing, discount or specific terms of a contract with a named customer?"},
    {"id": "fin", "name": "Unpublished financials",
     "question": "Does the text contain company financial results or forecasts (revenue, profit, guidance) that have "
                 "not yet been publicly released?"},
]

CUSTOMERS = ["Norvale Foods", "Hanbit Logistics", "Brightwater Clinics", "Arcturus Retail", "Solenne Motors"]
KO_CUSTOMERS = ["한빛물류", "대성푸드", "청람의료재단", "누리모빌리티", "새솔유통"]

T = {
    "kestrel": {
        "pos": [
            "Kestrel launch slipped to {month}; we'll announce the {partner} partnership at the same time. Keep this internal.",
            "Roadmap draft: Project Kestrel v1 ships offline payments in Q{q}, budget capped at ${m}M, {n} engineers.",
            "Can you turn these notes into a slide? Kestrel pilot with {partner} starts {month}, pricing ${p}/seat, not public yet.",
            "Write a commit message: 'Kestrel: hide unreleased instant-settlement feature behind flag until {month} launch'.",
            "Kestrel headcount plan for next year: +{n} in Seoul, +{n2} in Singapore. Do not share outside leadership.",
            "Kestrel 프로젝트 출시일이 {month}로 확정됐습니다. {partner} 제휴는 출시 당일 발표 예정이니 외부 공유 금지.",
            "내부 메모: Kestrel 2단계 예산 {m}억 원, 인력 {n}명 증원. 아직 미공개 일정입니다.",
            "Kestrel 신규 기능(오프라인 결제) 로드맵 정리해줘. Q{q} 베타, 연말 정식 출시 계획.",
        ],
        "neg": [
            "How do I configure Kestrel in ASP.NET Core to listen on port {port} with HTTPS?",
            "Kestrel throws 'Request body too large'; where do I set MaxRequestBodySize?",
            "Is it OK to expose Kestrel directly to the internet or should I put nginx in front of it?",
            "The kestrel is a small falcon that hovers while hunting; it is common across Europe.",
            "builder.WebHost.ConfigureKestrel(o => o.Limits.MaxConcurrentConnections = {n});",
            "Benchmark: Kestrel served {n}k requests/s on 8 cores in the TechEmpower plaintext test.",
            "Kestrel 웹 서버에서 HTTP/2 를 켜려면 appsettings.json 에 어떤 설정이 필요한가요?",
            "ASP.NET Core 의 Kestrel 은 기본으로 포트 {port} 를 사용합니다. 리버스 프록시 구성 방법을 알려주세요.",
            "황조롱이(kestrel)는 정지 비행을 하며 먹이를 찾는 맹금류입니다.",
        ],
    },
    "comp": {
        "pos": [
            "{ename}'s base salary goes from ${s}k to ${s2}k next cycle, plus a {b}% bonus. Please update the sheet.",
            "Performance calibration: {ename} rated 'Below expectations', put on a PIP starting {month}.",
            "Draft an email telling {ename} their equity refresh is {n} RSUs over 4 years.",
            "Summary of {ename}'s review: strong delivery, weak communication, final rating 3/5, no promotion this year.",
            "{kname} 책임 연봉 {w}만 원에서 {w2}만 원으로 조정, 성과급 {b}% 지급 예정입니다.",
            "인사평가 결과: {kname} 선임 C등급, 이번 승진 대상에서 제외. 본인 통보 전입니다.",
            "{kname} 대리 스톡옵션 {n}주 부여 건 품의서 작성해줘.",
            "올해 {kname} 과장 평가 코멘트 요약: 목표 달성률 {pct}%, 최종 등급 B.",
        ],
        "neg": [
            "What are good tips for negotiating a higher salary when changing jobs?",
            "According to public survey data, the median software engineer salary rose {pct}% in {year}.",
            "def compute_bonus(base: float, rate: float) -> float:\n    return round(base * rate, 2)",
            "Template for a performance review: 1) goals, 2) achievements, 3) growth areas, 4) next steps.",
            "Our API performance review found p99 latency of {n} ms; we should add caching.",
            "How should a manager prepare for a difficult performance conversation?",
            "연봉 협상할 때 이직 사유는 어떻게 설명하는 게 좋을까요?",
            "인사평가 양식 초안: 목표, 성과, 역량, 개선점 항목으로 구성해줘.",
            "코드 리뷰에서 성능(performance) 개선 포인트를 정리했습니다: N+1 쿼리 제거.",
        ],
    },
    "contract": {
        "pos": [
            "Our renewal with {cust} is ${m}M/year for 3 years with a {pct}% discount and net-60 payment terms.",
            "{cust} signed: ${p}k ARR, uncapped overage at ${r} per GB, termination for convenience after 12 months.",
            "Write a summary of the {cust} MSA: liability cap ${m}M, exclusivity in APAC, auto-renewal.",
            "Pricing exception approved for {cust}: {pct}% off list, price locked until {year2}.",
            "{kcust}와의 계약 금액은 연 {m}억 원, 계약 기간 3년, 할인율 {pct}% 입니다.",
            "{kcust} 갱신 조건: 단가 {w}원/건, 최소 물량 보장, 위약금 {pct}%.",
            "{kcust} 견적 최종안: 총액 {m}억 원, 선금 30%, 잔금은 검수 후 지급.",
        ],
        "neg": [
            "What clauses should a standard SaaS master services agreement contain?",
            "Contract template outline: parties, scope, fees, term, termination, liability, governing law.",
            "Tips for negotiating payment terms with enterprise customers?",
            "The MIT license lets you use, copy, modify and distribute the software with attribution.",
            "Our public pricing page lists the Team plan at ${p} per user per month.",
            "class Contract(models.Model):\n    amount = models.DecimalField(max_digits=12, decimal_places=2)\n    term_months = models.IntegerField()",
            "계약서 표준 양식에 들어가야 할 조항 목록을 알려줘.",
            "고객사와 단가 협상할 때 유의할 점은?",
            "오픈소스 Apache 2.0 라이선스의 특허 조항은 어떤 의미인가요?",
        ],
    },
    "fin": {
        "pos": [
            "Pre-release numbers: Q{q} revenue ${m}M, up {pct}% YoY; earnings call is next {day}. Keep confidential.",
            "Draft the board deck: unaudited Q{q} operating margin {pct}%, full-year guidance cut to ${m}M.",
            "We missed the quarter: bookings ${m}M vs ${m2}M plan. This goes public with the {month} filing.",
            "Rewrite this for the investor letter (not out yet): net loss narrowed to ${m}M in Q{q}.",
            "공시 전 자료: {q}분기 매출 {m}억 원, 영업이익률 {pct}%. 외부 유출 금지.",
            "다음 주 실적 발표 전 내부 집계: 순이익 {m}억 원으로 전년 대비 {pct}% 감소.",
            "이사회 보고용(미공개): 연간 매출 가이던스를 {m}억 원으로 하향 조정 예정.",
        ],
        "neg": [
            "Apple reported fiscal {year} revenue in its published 10-K; how do I parse the XBRL?",
            "As disclosed in last year's annual report, revenue grew {pct}% year over year.",
            "Explain the difference between operating margin and net margin.",
            "def yoy_growth(cur, prev):\n    return (cur - prev) / prev * 100",
            "How do I build a DCF model in a spreadsheet?",
            "The company's Q{q} {year} results, published in February, showed a {pct}% increase in revenue.",
            "삼성전자가 공시한 {year}년 연간 실적 자료는 어디서 볼 수 있나요?",
            "영업이익률과 순이익률의 차이를 설명해줘.",
            "작년 사업보고서에 공개된 매출 성장률 {pct}% 를 차트로 그려줘.",
        ],
    },
}


def fill(g, tpl):
    vals = {"month": g.pick(["March", "April", "May", "June", "September", "October", "3월", "5월", "9월"]),
            "partner": g.pick(["Hyundai Card", "Lotte", "KB", "Shinhan", "a large telco"]), "q": g.r.randint(1, 4),
            "m": g.r.randint(2, 90), "m2": g.r.randint(2, 90), "n": g.r.randint(3, 40), "n2": g.r.randint(2, 20),
            "p": g.r.randint(5, 900), "r": round(g.r.uniform(0.01, 0.5), 2), "port": g.pick([5000, 5001, 8080, 443]),
            "s": g.r.randint(90, 180), "s2": g.r.randint(120, 240), "b": g.r.randint(5, 30), "w": g.won(4000, 12000),
            "w2": g.won(5000, 14000), "pct": g.r.randint(3, 35), "year": g.r.randint(2019, 2025), "year2": g.r.randint(2027, 2030),
            "ename": g.en_name(), "kname": g.ko_name(), "cust": g.pick(CUSTOMERS), "kcust": g.pick(KO_CUSTOMERS),
            "day": g.pick(["Tuesday", "Thursday"])}
    return tpl.format(**vals)


def build(g):
    out = []
    for rule in RULES:
        for side, label in (("pos", 1), ("neg", 0)):
            tpls = T[rule["id"]][side]
            for i in range(N_PER_SIDE):
                tpl = tpls[i % len(tpls)]
                lang = "ko" if any("가" <= c <= "힣" for c in tpl) else "en"
                out.append({"id": f"rules-{rule['id']}-{side}{i}", "set": "rules", "lang": lang, "label": label,
                            "rule": rule["id"], "cats": [], "group": side, "text": fill(g, tpl)})
    return out


if __name__ == "__main__":
    recs = build(Gen(f"{SEED}-rules"))
    os.makedirs(SETS, exist_ok=True)
    with open(os.path.join(SETS, "rules.jsonl"), "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {}
    for r in recs:
        k = f"{r['rule']}:{r['group']}:{r['lang']}"
        counts[k] = counts.get(k, 0) + 1
    print(len(recs), sorted(counts.items()))
