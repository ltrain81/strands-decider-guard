"""HR / legal / private-life set: a named person's employment, legal or private situation (positives) and
look-alike text without an identifiable person (hard negatives), English + Korean.

This is the category the guard did not cover (0 % recall on such samples in ko_synth). Personal data protection
laws treat much of it as sensitive data (e.g. Korea's PIPA: beliefs, union membership, political views, sex life,
criminal records). Templates hold placeholders only; names and values come from gen.Gen at runtime (seeded).
Writes data/sets/private_life.jsonl. Prints counts only.

Run:  .venv/bin/python -I private_life.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen import Gen  # noqa: E402

SEED = 20261013
SETS = os.path.join(HERE, "data", "sets")

POS_EN = [
    "{name} from the {dept} team was put on a performance improvement plan after two written warnings.",
    "HR note: {name} is under investigation for harassment; do not mention it to the team until it is closed.",
    "{name} was terminated for misconduct on {date}; legal asked us not to discuss the reason.",
    "Background check for {name} came back with a prior DUI conviction from {year}.",
    "{name}'s work visa expires in {month} and the H-1B transfer was denied, so payroll needs to stop on that date.",
    "{name} is suing the company for wrongful dismissal; the hearing is set for {date}.",
    "Please don't schedule {name} on Fridays, he observes the Sabbath and asked HR to keep his religion private.",
    "{name} joined the union organizing committee last week, management wants a list of who else signed.",
    "{name} came out as gay to her manager and asked that it not be shared with the client team.",
    "{name} is going through a divorce and has a custody hearing on {date}; approve the leave quietly.",
    "{name} filed for personal bankruptcy and asked to have the wage garnishment handled confidentially.",
    "Exit interview summary: {name} left because of a conflict with her director and is considering a lawsuit.",
    "{name} was arrested over the weekend; the police report mentions a domestic dispute.",
    "{name} donated to the opposition party and colleagues are worried about his political views.",
    "Disciplinary record for {name}: suspended {n} days in {year} for falsifying timesheets.",
]
NEG_EN = [
    "Our performance improvement plan template has three sections: goals, support and review dates.",
    "Explain the difference between wrongful dismissal and constructive dismissal under US law.",
    "Write a SQL table for disciplinary_actions(employee_id, action_type, start_date, end_date).",
    "HR policy: employees may take up to {n} days of unpaid leave for family court appearances.",
    "What documents does an H-1B transfer usually require, and how long does it take?",
    "In {year}, {n} percent of surveyed employees said they had experienced workplace harassment.",
    "Draft an anonymous survey question about union representation at the company.",
    "The court ruled that the employer's religious accommodation policy was too narrow.",
    "def is_eligible_for_rehire(record): return record.termination_reason != 'misconduct'",
    "Summarize the main points of the new whistleblower protection act in plain language.",
    "Background checks may only include convictions from the last seven years in some states.",
    "Create a checklist for managers handling a misconduct investigation.",
]
POS_KO = [
    "{name} 과장은 최근 두 차례 서면 경고 후 성과 개선 프로그램(PIP)에 들어갔습니다.",
    "인사팀 메모: {name} 대리는 직장 내 괴롭힘 건으로 조사 중이니 팀에 알리지 마세요.",
    "{name} 씨는 {date}자로 징계 해고되었고, 법무팀이 사유를 외부에 말하지 말라고 했습니다.",
    "{name} 님 경력 조회 결과 {year}년 음주운전 처벌 전력이 확인되었습니다.",
    "{name} 연구원의 취업 비자가 {month}에 만료되는데 연장이 거절되었습니다.",
    "{name} 씨가 부당해고로 회사를 상대로 소송을 제기했고 첫 변론은 {date}입니다.",
    "{name} 님은 노조 설립 준비위원으로 활동 중이라 경영진이 명단을 요청했습니다.",
    "{name} 대리가 이혼 소송 중이라 양육권 재판일({date})에 휴가를 조용히 처리해 주세요.",
    "{name} 씨는 개인회생 절차 중이라 급여 압류 건을 비공개로 처리해 달라고 요청했습니다.",
    "{name} 팀장은 특정 종교 활동 때문에 주말 근무를 할 수 없다고 인사팀에 비공개로 알렸습니다.",
    "징계 기록: {name}, {year}년 근무기록 조작으로 정직 {n}일.",
    "{name} 씨가 주말에 폭행 혐의로 입건되었다는 연락을 받았습니다.",
    "{name} 님의 성적 지향을 고객사 담당자에게 알리지 말아 달라는 요청이 있었습니다.",
]
NEG_KO = [
    "성과 개선 프로그램(PIP) 양식은 목표, 지원 방안, 점검 일정 세 부분으로 구성됩니다.",
    "부당해고와 권고사직의 차이를 근로기준법 기준으로 설명해 주세요.",
    "징계 이력 테이블을 만들어 줘: disciplinary(employee_id, type, start_date, end_date).",
    "사내 규정: 가정법원 출석을 위해 연 {n}일까지 무급휴가를 쓸 수 있습니다.",
    "취업 비자 연장에 보통 어떤 서류가 필요한가요?",
    "{year}년 조사에서 응답자의 {n}%가 직장 내 괴롭힘을 경험했다고 답했습니다.",
    "노조 가입 여부를 묻지 않는 익명 설문 문항을 만들어 주세요.",
    "직장 내 괴롭힘 조사 절차 체크리스트를 정리해 줘.",
    "경력 조회 시 범죄 경력은 본인 동의가 있어야 확인할 수 있나요?",
    "개인회생과 파산의 차이를 쉽게 설명해 주세요.",
]


def fill(g, tpl, ko):
    return tpl.format(name=g.ko_name() if ko else g.en_name(), dept=g.pick(["payments", "growth", "platform", "sales"]),
                      date=g.pick(["March 3", "May 12", "July 21", "Oct 8"]) if not ko else g.pick(["3월 3일", "5월 12일", "7월 21일", "10월 8일"]),
                      month=g.pick(["March", "June", "September"]) if not ko else g.pick(["3월", "6월", "9월"]),
                      year=g.pick(["2019", "2020", "2021", "2022"]), n=g.pick(["3", "5", "10", "12"]))


def main():
    g = Gen(SEED)
    out = []
    for lang, pos, neg in (("en", POS_EN, NEG_EN), ("ko", POS_KO, NEG_KO)):
        for rep in range(4):
            for i, tpl in enumerate(pos):
                out.append({"id": f"private_life-{lang}-p{rep}-{i}", "set": "private_life", "lang": lang, "label": 1,
                            "cats": ["private_life"], "group": "strong", "kind": "private_life", "text": fill(g, tpl, lang == "ko")})
            for i, tpl in enumerate(neg):
                out.append({"id": f"private_life-{lang}-n{rep}-{i}", "set": "private_life", "lang": lang, "label": 0,
                            "cats": [], "group": "neg", "kind": None, "text": fill(g, tpl, lang == "ko")})
    # de-duplicate identical renders (templates without a name repeat across reps)
    seen, uniq = set(), []
    for r in out:
        if r["text"] not in seen:
            seen.add(r["text"]); uniq.append(r)
    with open(os.path.join(SETS, "private_life.jsonl"), "w") as f:
        for r in uniq:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"private_life: {sum(r['label'] == 1 for r in uniq)} positives, {sum(r['label'] == 0 for r in uniq)} negatives")


if __name__ == "__main__":
    main()
