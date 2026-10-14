import assert from 'node:assert/strict';
import { test } from 'node:test';
import { durationLabel, pendingReason } from '../src/lib/interviewList.ts';

/** 목록 한 줄. 서버가 주는 모양 그대로다 (counts 는 요약이 READY 일 때만 온다). */
const row = (over) => ({
  interviewId: 'itv_1',
  candidateName: '김지원',
  role: '백엔드 개발자',
  interviewer: { nickname: '정태' },
  interviewedAt: '2026-10-09T01:00:00+00:00',
  durationSec: 1800,
  reviewStatus: 'PENDING',
  summaryStatus: 'READY',
  counts: { coverageConfirmed: 2, coverageTotal: 5, findings: 4, needsReview: 3, adopted: 1 },
  ...over,
});

test('집계가 있으면 숫자를 적고, 없으면 왜 없는지를 적는다', () => {
  assert.equal(pendingReason(row()), null);
  assert.equal(pendingReason(row({ counts: null, summaryStatus: 'PROCESSING' })), '정리 중');
  assert.equal(pendingReason(row({ counts: null, summaryStatus: 'FAILED' })), '정리 실패');
});

test('요약 상태를 면접 시각보다 먼저 본다', () => {
  // 아무도 입장하지 않고 끝낸 면접은 시각이 없다(서버 `_timing`). 시각을 먼저 보면
  // 정리가 실패한 면접을 「면접 전」이라고 말해 — 끝났는데 안 끝났다고 하는 셈이다.
  assert.equal(
    pendingReason(row({ counts: null, summaryStatus: 'FAILED', interviewedAt: null })),
    '정리 실패',
  );
  assert.equal(
    pendingReason(row({ counts: null, summaryStatus: 'PROCESSING', interviewedAt: null })),
    '정리 중',
  );
});

test('아직 안 본 면접 · 진행 중 · 요약 없음을 구분한다', () => {
  // 세션조차 없다
  assert.equal(
    pendingReason(
      row({ counts: null, summaryStatus: null, interviewedAt: null, durationSec: null }),
    ),
    '면접 전',
  );
  // 시작은 했는데 길이가 없다 = 끝나지 않았다
  assert.equal(
    pendingReason(row({ counts: null, summaryStatus: null, durationSec: null })),
    '진행 중',
  );
  // 끝났는데 요약 자리가 아직 없다. 「정리 중」이면 돌지도 않는 것을 돈다고 말한다.
  assert.equal(pendingReason(row({ counts: null, summaryStatus: null })), '정리 전');
});

test('1분 미만을 0분으로 적지 않는다', () => {
  assert.equal(durationLabel(null), null);
  for (const sec of [0, 1, 29, 59]) assert.equal(durationLabel(sec), '1분 미만');
  assert.equal(durationLabel(60), '1분');
  assert.equal(durationLabel(90), '2분');
  assert.equal(durationLabel(1800), '30분');
});
