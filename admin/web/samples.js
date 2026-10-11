// Rule templates and sample texts for the Test tab (all values are synthetic).
// Kept separate from app.js so they are easy to edit or translate.

const TEMPLATES = {
  en: [
    { name: 'Unreleased project details', question: "Does the text include unreleased schedules, revenue or launch plans for the internal project 'Phoenix' (PHX)?" },
    { name: 'Employee salary / reviews', question: 'Does the text include an employee\'s salary, compensation or performance review?' },
    { name: 'Customer contract terms', question: 'Does the text include contract amounts or terms agreed with a customer?' },
    { name: 'Unpublished financials', question: 'Does the text include revenue, profit or other financial figures that are not yet public?' },
  ],
  ko: [
    { name: '사내 프로젝트 미공개 정보', question: "사내 프로젝트 'Phoenix(피닉스)'의 미공개 일정, 매출, 출시 계획이 포함되어 있나요?" },
    { name: '직원 급여·인사 정보', question: '직원의 급여, 연봉, 인사 평가 정보가 포함되어 있나요?' },
    { name: '고객사 계약 조건', question: '고객사와의 계약 금액이나 계약 조건이 포함되어 있나요?' },
    { name: '미공개 실적', question: '공시 전 매출, 영업이익 등 미공개 실적 수치가 포함되어 있나요?' },
  ],
};

const SAMPLES = {
  en: [
    { label: 'Customer list', text: 'customer_id,name,phone,email\nC-1001,Jane Doe,+1-415-555-0199,jane@acme.com' },
    { label: 'Support note', text: 'Support note: customer Mark Chen is being treated for depression and asked us not to call at night.' },
    { label: 'Code (schema)', text: 'CREATE TABLE customers (id INT, name VARCHAR(100), phone VARCHAR(20), email VARCHAR(255));' },
    { label: 'Internal project', text: 'Phoenix launches next March; Q1 revenue is projected at $9M.' },
    { label: 'General question', text: 'Show me an S3 bucket policy that allows cross-account access.' },
  ],
  ko: [
    { label: '고객 명단', text: 'customer_id,name,phone,email\nC-1001,김민수,010-2345-6789,minsu.kim@example.com' },
    { label: '상담 메모', text: '상담 메모: 고객 정우성님(40대)은 최근 우울증 치료 중이라 야간 연락을 원하지 않음.' },
    { label: '코드 (스키마)', text: 'CREATE TABLE customers (id INT, name VARCHAR(100), phone VARCHAR(20), email VARCHAR(255));' },
    { label: '사내 프로젝트', text: 'Phoenix 는 내년 3월 출시 예정이고 1분기 예상 매출은 120억입니다.' },
    { label: '일반 질문', text: 'S3 버킷 정책에서 교차 계정 접근을 허용하는 예시를 보여줘.' },
  ],
};
