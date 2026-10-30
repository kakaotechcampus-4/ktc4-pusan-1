import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reportBlockReason, reportIsStale } from '../src/lib/reportState.ts';

const review = {
  reviewStatus: 'CONFIRMED',
  sessionId: 'ses_1',
  reviewedAt: '2026-10-30T10:00:00Z',
  findings: [{ state: 'ADOPTED' }],
};
const report = { status: 'READY', sessionId: 'ses_1', generatedAt: '2026-10-30T10:01:00Z' };
test('검토 완료와 포함한 내용이 있어야 생성할 수 있다', () => {
  assert.equal(reportBlockReason(review), null);
  assert.ok(reportBlockReason(undefined));
  assert.ok(reportBlockReason({ ...review, reviewStatus: 'IN_REVIEW' }));
  assert.ok(reportBlockReason({ ...review, findings: [] }));
});
test('다른 세션이나 리포트 생성 후 바뀐 검토를 최신 리포트로 표시하지 않는다', () => {
  assert.equal(reportIsStale(report, review), false);
  assert.equal(reportIsStale(report, { ...review, sessionId: 'ses_2' }), true);
  assert.equal(reportIsStale(report, { ...review, reviewStatus: 'IN_REVIEW' }), true);
  assert.equal(reportIsStale(report, { ...review, reviewedAt: '2026-10-30T10:02:00Z' }), true);
});

test('생성 후 메모를 수정한 리포트를 현재 메모와 같은 결과로 표시하지 않는다', () => {
  assert.equal(
    reportIsStale({ ...report, memo: '이전 메모' }, { ...review, memo: '최신 메모' }),
    true,
  );
});
