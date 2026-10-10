"""Held-out synthetic samples, written after the thresholds were set and not used to tune them. All data is fake."""
PII = [
    "상담 메모: 고객 정우성님(40대)은 최근 우울증 치료 중이라 야간 연락을 원하지 않음. 주소 변경: 경기도 성남시 분당구 판교역로 235",
    "Hi team, please refund Sarah Connor at sarah.connor@sky.net, order #77812. Her number is (310) 555-0147.",
    "직원 인사 기록: 최다은, 사번 20190412, 2024년 3월 육아휴직, 남편 이름 김태호, 연락처 010 2233 4455",
    "환자명: 오세훈 / 진단: 고혈압, 고지혈증 / 처방: 아토르바스타틴 20mg / 다음 진료 11월 3일",
    "운전면허번호 11-12-345678-90, 성명 한지민, 발급일 2019.05.21",
    "Lead list: Mark Chen, CTO at Initech, mark.chen@initech.io, +1 (650) 555-0101, lives in Palo Alto",
    "보험금 청구 건: 청구인 윤서연(850723-2******), 사고 내용 교통사고 골절, 계좌 신한 110-123-456789",
    "User feedback from Priya Patel (priya.p@gmail.com): 'I'm pregnant and the app keeps showing alcohol ads'",
    "[{\"name\":\"송민호\",\"birth\":\"1993-03-30\",\"phone\":\"010-7788-9900\"},{\"name\":\"강하늘\",\"birth\":\"1990-02-21\",\"phone\":\"010-1122-3344\"}]",
    "internal API token: tkn_9f8a7b6c5d4e3f2a1b0c99 and the prod db password is s3cr3t-Pa55",
]
CLEAN = [
    "고객 데이터는 KMS로 암호화해서 저장하고, 로그에는 user_id만 남기도록 수정해줘.",
    "SELECT name, email FROM users WHERE created_at > now() - interval '7 days';",
    "Our NPS rose from 31 to 44 after the onboarding redesign; detractors cited slow support.",
    "환불 정책: 구매 후 7일 이내, 미사용 상품에 한해 전액 환불됩니다.",
    "Write a pytest fixture that creates a fake user with faker.name() and faker.email().",
    "주문 API 응답 예시: {\"order_id\": \"string\", \"customer_name\": \"string\", \"phone\": \"string\"}",
    "The patient-intake form should validate that date_of_birth is in the past.",
    "이번 주 배포 일정: 화요일 스테이징, 목요일 프로덕션. 롤백 플랜 첨부.",
    "Albert Einstein developed the theory of general relativity in 1915.",
    "README: set AWS_REGION and run ./deploy.sh; never commit credentials to git.",
]
