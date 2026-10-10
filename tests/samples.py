"""Synthetic test data. Every name, number and address here is fake."""
PII = [
    "고객 김민수 (010-2345-6789, minsu.kim@example.com) 님의 배송지는 서울시 강남구 테헤란로 123 입니다.",
    "주민등록번호 900101-1234567 확인 부탁드립니다.",
    "홍길동 환자는 2형 당뇨 진단을 받았고 인슐린 처방 중입니다.",
    "카드번호 4111-1111-1111-1111, 유효기간 12/27로 결제해주세요.",
    "환불 계좌: 국민은행 123456-78-901234 예금주 이영희",
    "Customer John Smith, SSN 123-45-6789, lives at 42 Elm St, Springfield.",
    "id,name,email,phone\n1,Jane Doe,jane@acme.com,+1-415-555-0199\n2,Bob Lee,bob@acme.com,+1-212-555-0142",
    "어제 상담한 박지영 고객이 남편과 이혼 소송 중이라 연락처 변경을 요청했어요. 새 번호는 010-9876-5432.",
    '{"user_id": 88123, "name": "최수진", "phone": "01055556666", "addr": "부산 해운대구 우동 1234"}',
    "Patient Maria Garcia (DOB 03/14/1985) was diagnosed with HIV in 2021.",
    "여권번호 M12345678, 이름 JUNG HOSEOK, 생년월일 1994-02-18",
    "이 고객 정보로 환불 메일 써줘: 이름 정우성, 이메일 woosung.j@naver.com, 주문번호 A-20391",
]
SECRET = [
    "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "db password is Hunter2!prod, user admin",
]
CLEAN = [
    "이 함수에서 email 필드 validation 로직 리팩토링 해줘",
    "def send_email(user):\n    return smtp.send(user.email, subject)",
    "다음 분기 매출 리포트 초안 작성해줘. 지역별 합계만 필요해.",
    "Explain how to configure an S3 bucket policy for cross-account access.",
    "CREATE TABLE customers (id INT, name VARCHAR(100), phone VARCHAR(20), email VARCHAR(255));",
    "고객 이탈률이 3월에 12%로 증가했습니다. 원인 분석 부탁드립니다.",
    "전화번호 형식은 010-XXXX-XXXX 로 마스킹해서 저장하세요.",
    "Tim Cook is the CEO of Apple.",
    "서울 지역 고객 1,234명 중 30대 비율은 41%입니다.",
    "정규식 ^\\d{6}-\\d{7}$ 로 주민번호 형식을 검증하는 코드 작성해줘",
    "Fix the null pointer exception in OrderService.java line 42.",
    "내일 오후 3시 회의실 예약해줘. 안건은 신규 기능 리뷰.",
    "git log --since=2024-01-01 --until=2024-03-31 --oneline | wc -l",
    "Order total was 1234567890 KRW across 2024-05-01 to 2024-05-31.",
]
