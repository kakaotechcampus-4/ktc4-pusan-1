import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reportFileName, reportToMarkdown } from '../src/lib/reportMarkdown.ts';

const statement = (over = {}) => ({
  text: '결제 장애 때 큐를 분리해 정산 지연을 줄였다.',
  findingId: 'f1',
  findingType: 'COMPETENCY_EVIDENCE',
  source: null,
  quote: null,
  transcript: null,
  atSec: null,
  ...over,
});
const report = (over = {}) => ({
  status: 'READY',
  interviewId: 'int_1',
  sessionId: 'ses_1',
  generatedAt: '2026-11-08T03:00:00Z',
  reviewStatus: 'CONFIRMED',
  candidate: { name: '김지원', role: '백엔드 개발자' },
  interviewer: { nickname: '면접관A' },
  interviewedAt: '2026-11-07T05:30:00Z',
  memo: '',
  overview: '장애 대응 경험이 구체적이다.',
  competencies: [
    {
      name: '문제 해결',
      required: true,
      state: 'COVERED',
      confirmed: [statement({ transcript: '정산 배치가\n밀렸을 때 큐를 나눴습니다.', atSec: 134 })],
      unconfirmed: [
        statement({
          findingType: 'CLAIM_UNVERIFIED',
          text: '처리량 수치는 확인하지 못했다.',
          source: '이력서',
          quote: '처리량 3배 향상',
        }),
      ],
      nextQuestions: ['처리량을 어떻게 측정했나요?'],
    },
    {
      name: '협업',
      required: false,
      state: 'MISSING',
      confirmed: [],
      unconfirmed: [],
      nextQuestions: ['갈등을 조율한 경험이 있나요?'],
    },
  ],
  failureReason: null,
  ...over,
});

test('화면과 같은 순서로 메모 · 요약 · 역량별 문장과 다음 질문을 옮긴다', () => {
  const md = reportToMarkdown(report());
  const order = [
    '# 김지원 · 면접 리포트',
    '- 현재 설정 직무: 백엔드 개발자',
    '- 면접관: 면접관A',
    '## 면접관 메모',
    '작성된 메모가 없습니다.',
    '## 면접 요약',
    '## 문제 해결 (필수)',
    '### 확인된 점',
    '- **면접 답변** 결제 장애 때 큐를 분리해 정산 지연을 줄였다.',
    '  - 면접 답변 (02:14): “정산 배치가 밀렸을 때 큐를 나눴습니다.”',
    '### 확인되지 않은 점',
    '- **추가 확인 필요** 처리량 수치는 확인하지 못했다.',
    '  - 이력서: “처리량 3배 향상”',
    '### 다음에 물어볼 것',
    '- 처리량을 어떻게 측정했나요?',
    '## 협업 (우대)',
    '_이번 면접에서 다루지 않음_',
    '- 갈등을 조율한 경험이 있나요?',
    'IRYA가 면접관이 선택한 내용을 정리했습니다. 평가 점수가 아닙니다.',
  ];
  let at = -1;
  for (const line of order) {
    const next = md.indexOf(line, at + 1);
    assert.ok(next > at, `순서가 어긋남: ${line}`);
    at = next;
  }
  assert.ok(!md.includes('### 확인된 점\n\n### 다음에'), '빈 역량 섹션은 쓰지 않는다');
});

test('이름 · 시각이 없어도 깨지지 않고 메모 줄바꿈은 강제 줄바꿈으로 남긴다', () => {
  const md = reportToMarkdown(
    report({
      candidate: { name: null, role: 'PM' },
      interviewedAt: null,
      generatedAt: null,
      memo: '첫 줄\n둘째 줄',
    }),
  );
  assert.ok(md.startsWith('# 이름 없는 지원자 · 면접 리포트'));
  assert.ok(!md.includes('면접 일시'));
  assert.ok(md.includes('첫 줄  \n둘째 줄'));
});

test('파일 이름에서 운영체제가 받지 않는 글자를 뺀다', () => {
  assert.equal(
    reportFileName(report({ candidate: { name: '김/지원:*', role: 'x' } }), 'md'),
    `IRYA_리포트_김_지원_${new Date('2026-11-07T05:30:00Z').toLocaleDateString('sv-SE')}.md`,
  );
  assert.equal(
    reportFileName(
      report({ candidate: { name: null, role: 'x' }, interviewedAt: null, generatedAt: null }),
      'md',
    ),
    'IRYA_리포트_지원자.md',
  );
});
