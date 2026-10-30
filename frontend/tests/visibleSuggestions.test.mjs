import assert from 'node:assert/strict';
import { test } from 'node:test';
import { visibleSuggestions } from '../src/lib/visibleSuggestions.ts';

const question = (id, pinned = false) => ({
  id: String(id),
  content: `질문 ${id}`,
  pinned,
  createdAt: new Date(Date.UTC(2026, 9, 30, 0, id)).toISOString(),
});

test('고정한 질문을 모두 남기고 미고정 질문은 최신 다섯 개만 보여준다', () => {
  const source = Array.from({ length: 9 }, (_, i) => question(i, i < 2));
  assert.deepEqual(
    visibleSuggestions(source).map((q) => q.id),
    ['1', '0', '8', '7', '6', '5', '4'],
  );
  assert.equal(source.length, 9);
  assert.equal(source[0].pinned, true);
});

test('오래된 질문의 고정을 풀면 최신 다섯 개 밖으로 빠진다', () => {
  const source = Array.from({ length: 7 }, (_, i) => question(i));
  assert.deepEqual(
    visibleSuggestions(source).map((q) => q.id),
    ['6', '5', '4', '3', '2'],
  );
  assert.deepEqual(visibleSuggestions([]), []);
  assert.equal(visibleSuggestions(source.slice(0, 5)).length, 5);
});

test('같은 시각의 질문도 순서가 고정되고 입력 배열을 바꾸지 않는다', () => {
  const source = [question(1), { ...question(1), id: '2' }];
  assert.deepEqual(
    visibleSuggestions(source).map((q) => q.id),
    ['2', '1'],
  );
  assert.deepEqual(
    source.map((q) => q.id),
    ['1', '2'],
  );
});
