import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FALLBACK_CANDIDATE } from '../src/lib/candidateName.ts';
import { toLegacyReview } from '../src/lib/reviewCompat.ts';

const MOMENT = {
  id: 'mom_qa_utt_TR_a_0001',
  atSec: 15,
  label: '자기소개',
  question: '간단히 자기소개 부탁드립니다.',
  answer: '실시간 스트리밍 파이프라인을 주로 맡아 왔다고 소개했습니다.',
  competencies: ['서비스 설계'],
  bookmarked: false,
};

// BE 가 지금 내는 READY 응답 (#137 1-2 · #163)
const READY = {
  status: 'READY',
  summaryStatus: 'READY',
  interviewId: 'int_1',
  sessionId: 'ses_1',
  candidate: { name: '김도현', role: '백엔드 개발자' },
  interviewer: { nickname: '면접관' },
  interviewedAt: '2026-09-18T05:00:00Z',
  durationSec: 634,
  reviewStatus: 'PENDING',
  reviewedAt: null,
  memo: '',
  summary: { overview: '지원자는 캐시를 적용한 경험을 설명했습니다.', keyPoints: ['캐시'] },
  coverage: [],
  moments: [MOMENT],
  findings: [],
};

test('새 READY 응답을 지금 면접 기록 화면의 모양으로 옮긴다', () => {
  assert.deepEqual(toLegacyReview(READY), {
    status: 'READY',
    interviewId: 'int_1',
    candidate: { name: '김도현', role: '백엔드 개발자' },
    durationSec: 634,
    // 녹화는 상세에 실리지 않는다 — 녹화 API 로 받는 건 FE 전환 작업이다.
    recording: null,
    moments: [MOMENT],
    aiReview: { paragraphs: ['지원자는 캐시를 적용한 경험을 설명했습니다.'] },
  });
});

test('요약이 FAILED 면 서술이 비고, 이름 · 길이가 없으면 화면의 기본값을 쓴다', () => {
  const failed = {
    ...READY,
    summaryStatus: 'FAILED',
    summary: null,
    moments: [],
    candidate: { name: null, role: '' },
    durationSec: null,
  };

  const review = toLegacyReview(failed);

  assert.deepEqual(review.aiReview, { paragraphs: [] });
  assert.equal(review.candidate.name, FALLBACK_CANDIDATE);
  assert.equal(review.durationSec, 0);
});
