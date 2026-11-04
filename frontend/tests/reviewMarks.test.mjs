import assert from 'node:assert/strict';
import { test } from 'node:test';
import { applyMark, currentMark } from '../src/lib/reviewMarks.ts';

const review = () => ({
  findings: [
    { id: 'f1', state: 'PROPOSED' },
    { id: 'f2', state: 'ADOPTED' },
  ],
  moments: [
    { id: 'm1', bookmarked: false },
    { id: 'm2', bookmarked: true },
  ],
});

test('검토 항목은 state 만, 문답은 bookmarked 만 바꾼다', () => {
  const r = review();
  const adopted = applyMark(r, 'f1', { state: 'ADOPTED' });
  assert.deepEqual(
    adopted.findings.map((f) => f.state),
    ['ADOPTED', 'ADOPTED'],
  );
  assert.equal(adopted.moments, r.moments);

  const marked = applyMark(r, 'm1', { bookmarked: true });
  assert.deepEqual(
    marked.moments.map((m) => m.bookmarked),
    [true, true],
  );
  assert.equal(marked.findings, r.findings);
  // 원본은 그대로 — 캐시를 직접 고치면 실패 때 되돌릴 값이 사라진다.
  assert.equal(r.findings[0].state, 'PROPOSED');
});

test('되돌릴 값은 보낸 것과 같은 종류로 읽는다', () => {
  const r = review();
  assert.deepEqual(currentMark(r, 'f2', { state: 'REJECTED' }), { state: 'ADOPTED' });
  assert.deepEqual(currentMark(r, 'm2', { bookmarked: false }), { bookmarked: true });
  assert.equal(currentMark(r, 'nope', { state: 'ADOPTED' }), null);
});
