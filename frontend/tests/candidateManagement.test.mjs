import assert from 'node:assert/strict';
import { test } from 'node:test';
import { candidateRows, rangeSelection, delimitedCell } from '../src/lib/candidateManagement.ts';

const rows = Array.from({ length: 1000 }, (_, i) => ({
  interviewId: `int_${i}`,
  candidateName: i % 2 ? '김지원' : '이서준',
  reviewStatus: i % 2 ? 'CONFIRMED' : 'PENDING',
  summaryStatus: 'READY',
  interviewedAt: null,
  counts: { needsReview: i, adopted: i % 5 },
}));
test('천 건을 검색·필터·다중 정렬해도 원본과 면접 ID를 바꾸지 않는다', () => {
  const filtered = candidateRows(rows, { search: '김지원', review: 'CONFIRMED', summary: 'all' }, [
    { key: 'adopted', descending: true },
    { key: 'needsReview', descending: true },
  ]);
  assert.equal(filtered.length, 500);
  assert.equal(filtered[0].interviewId, 'int_999');
  assert.equal(rows[0].interviewId, 'int_0');
  assert.equal(rows.length, 1000);
});
test('범위 선택은 화면 순서의 ID에 적용하고 다른 페이지 선택을 보존한다', () => {
  const selected = rangeSelection(['c', 'a', 'b'], 'c', 'b', new Set(['outside']), true);
  assert.deepEqual([...selected], ['outside', 'c', 'a', 'b']);
  assert.deepEqual(
    [...rangeSelection(['c', 'a', 'b'], 'a', 'b', selected, false)],
    ['outside', 'c'],
  );
});
test('CSV·TSV의 줄바꿈·따옴표·수식 문자열을 안전하게 처리한다', () => {
  assert.equal(delimitedCell('가,나'), '"가,나"');
  assert.equal(delimitedCell('가\n"나"'), '"가\n""나"""');
  assert.equal(delimitedCell('=SUM(A1)'), "'=SUM(A1)");
  assert.equal(delimitedCell('가\t나', '\t'), '"가\t나"');
  assert.equal(delimitedCell(null), '');
});
