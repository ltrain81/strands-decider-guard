#!/usr/bin/env python3
"""Policy features against a running decider: category actions, allowlists, custom rules, validation."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guard"))
import guard_core as g

URL = sys.argv[1] if len(sys.argv) > 1 else None
fails = 0


def expect(name, text, want, policy=None):
    global fails
    r = g.check(text, URL, policy)
    ok = r["decision"] == want
    fails += not ok
    print(f"{'ok ' if ok else 'BAD'} {name:44} -> {r['decision']:5} (want {want})  {'; '.join(r['reasons'])[:90]}")


RRN = "주민등록번호 900101-1234567 확인 부탁드립니다."
HEALTH = "홍길동 환자는 우울증 치료 중이라 야간 연락 금지"
expect("default: resident id", RRN, "block")
expect("resident_id=ask, gov_id=ask", RRN, "ask", {"categories": {"resident_id": "ask", "gov_id": "ask"}})
expect("resident_id=allow, gov_id=allow", RRN, "allow", {"categories": {"resident_id": "allow", "gov_id": "allow"}})
expect("default: health", HEALTH, "block")
expect("health=allow", HEALTH, "allow", {"categories": {"health": "allow", "contact": "allow"}})
expect("health=ask", HEALTH, "ask", {"categories": {"health": "ask", "contact": "ask"}})
expect("company email, no allowlist", "고객 김민수님 kim.minsu@acme-corp.com 으로 환불 안내 메일 보내줘", "block")
expect("company email allowlisted", "고객 김민수님 kim.minsu@acme-corp.com 으로 환불 안내 메일 보내줘", "allow", {"allow": {"email_domains": ["acme-corp.com"], "terms": ["김민수"]}})
expect("test name allowlisted", "테스트 고객 홍길동 010-0000-0000 으로 가입 테스트", "allow",
       {"allow": {"terms": ["홍길동", "010-0000-0000"]}})
rule = {"custom_rules": [{"name": "Phoenix 미공개 정보", "question": "사내 프로젝트 'Phoenix(피닉스)'의 미공개 일정, 매출, 출시 계획이 포함되어 있나요?", "action": "block"}]}
expect("custom rule hit", "Phoenix 는 내년 3월 출시 예정이고 1분기 예상 매출은 120억입니다.", "block", rule)
expect("custom rule miss (library)", "phoenix 라이브러리로 웹소켓 서버를 만드는 방법 알려줘", "allow", rule)
expect("custom rule only, PII off", "김대리 올해 연봉 6,200만원, 평가 등급 B+", "ask",
       {"categories": {c["id"]: "allow" for c in g.CATEGORIES},
        "custom_rules": [{"name": "급여", "question": "직원의 급여, 연봉, 인사 평가 정보가 포함되어 있나요?", "action": "ask"}]})
for bad in ({"sensitivity": "max"}, {"categories": {"nope": "block"}}, {"categories": {"health": "deny"}}, {"custom_rules": [{"question": ""}]}):
    try:
        g.normalize_policy(bad)
        print("BAD validation accepted", bad); fails += 1
    except ValueError as e:
        print(f"ok  validation rejects {bad}: {e}")
print(f"\n{fails} failed")
sys.exit(1 if fails else 0)
