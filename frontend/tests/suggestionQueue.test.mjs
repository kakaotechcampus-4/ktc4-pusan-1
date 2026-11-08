import assert from 'node:assert/strict';
import { test } from 'node:test';
import { visibleSuggestions } from '../src/lib/suggestionQueue.ts';
import { queueOf, useInterviewStore } from '../src/stores/interviewStore.ts';

const question = (id) => ({
  id: String(id),
  content: `질문 ${id}`,
  pinned: false,
  createdAt: new Date(Date.UTC(2026, 10, 8, 0, id)).toISOString(),
});
const range = (from, to) => Array.from({ length: to - from }, (_, i) => question(from + i));
const store = useInterviewStore;
const shown = () => visibleSuggestions(queueOf(store.getState())).map((q) => q.id);
const push = (from, to) => range(from, to).forEach((q) => store.getState().addSuggestion(q));

test('고정하지 않은 질문은 최신 6개만 최신순으로 흐르고 보관은 10개로 제한한다', () => {
  store.getState().reset();
  assert.deepEqual(shown(), []);
  push(0, 30);
  assert.deepEqual(shown(), ['29', '28', '27', '26', '25', '24']);
  assert.equal(store.getState().suggestions.length, 10);
});

test('지운 칸은 비워 두고 다음 새 질문이 채우며 밀려난 질문은 되살리지 않는다', () => {
  store.getState().reset();
  push(0, 8);
  store.getState().dismissSuggestion('5');
  assert.deepEqual(shown(), ['7', '6', '4', '3', '2']);
  push(8, 9);
  assert.deepEqual(shown(), ['8', '7', '6', '4', '3', '2']);
  push(9, 10);
  assert.deepEqual(shown(), ['9', '8', '7', '6', '4', '3']);
  // 취소하면 원래 자리로 돌아오고 넘친 만큼 오래된 것이 빠진다.
  store.getState().undoDismissSuggestion();
  assert.deepEqual(shown(), ['9', '8', '7', '6', '5', '4']);
});

test('고정은 큐 밖 위에 남고 풀면 원래 자리로 돌아가거나 이미 지났으면 사라진다', () => {
  store.getState().reset();
  push(0, 6);
  store.getState().toggleSuggestionPin('1');
  store.getState().toggleSuggestionPin('4');
  assert.deepEqual(shown(), ['4', '1', '5', '3', '2', '0']);
  push(6, 12);
  assert.deepEqual(shown(), ['4', '1', '11', '10', '9', '8', '7', '6']);
  store.getState().toggleSuggestionPin('1');
  assert.deepEqual(shown(), ['4', '11', '10', '9', '8', '7', '6']);
  push(12, 13);
  store.getState().toggleSuggestionPin('4');
  assert.deepEqual(shown(), ['12', '11', '10', '9', '8', '7']);
});

test('표시 개수를 늘리면 보관 중인 질문으로 바로 채우고 줄이면 오래된 것부터 뺀다', () => {
  store.getState().reset();
  push(0, 20);
  store.getState().setSuggestionLimit(10);
  assert.equal(shown().length, 10);
  assert.equal(shown()[9], '10');
  store.getState().setSuggestionLimit(6);
  assert.deepEqual(shown(), ['19', '18', '17', '16', '15', '14']);
  store.getState().setSuggestionLimit(10);
  assert.equal(shown().length, 10);
  store.getState().setSuggestionLimit(6);
});

test('일시정지 중에는 보이는 목록이 그대로이고 다시 흐르면 최신으로 돌아간다', () => {
  store.getState().reset();
  push(0, 6);
  store.getState().toggleSuggestionsPaused();
  push(6, 20);
  assert.deepEqual(shown(), ['5', '4', '3', '2', '1', '0']);
  store.getState().dismissSuggestion('3');
  assert.deepEqual(shown(), ['5', '4', '2', '1', '0']);
  store.getState().toggleSuggestionsPaused();
  assert.deepEqual(shown(), ['19', '18', '17', '16', '15', '14']);
  assert.ok(store.getState().suggestions.length <= 10);
});

test('재조회는 끊긴 사이 질문만 붙이고 잘라낸 질문은 되살리지 않는다', () => {
  store.getState().reset();
  push(0, 20);
  store.getState().mergeSuggestions([...range(0, 20), question(20)]);
  assert.deepEqual(shown(), ['20', '19', '18', '17', '16', '15']);
  assert.ok(!store.getState().suggestions.some((q) => q.id === '0'));
});

test('같은 탭에서 다시 들어오면 지운 질문과 고정이 유지되고 다른 세션과 섞이지 않는다', () => {
  const memory = new Map();
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: (k) => memory.get(k) ?? null, setItem: (k, v) => memory.set(k, v) },
  });
  try {
    store.getState().reset();
    store.getState().setSession('ses_1');
    store.getState().mergeSuggestions(range(0, 4));
    store.getState().dismissSuggestion('3');
    store.getState().toggleSuggestionPin('0');

    // 새로고침: 화면 상태가 비고 조회 API 가 전부 다시 채운다.
    store.getState().reset();
    store.getState().setSession('ses_1');
    store.getState().mergeSuggestions(range(0, 4));
    assert.deepEqual(shown(), ['0', '2', '1']);

    store.getState().reset();
    store.getState().setSession('ses_2');
    assert.deepEqual(store.getState().hiddenSuggestionIds, []);
  } finally {
    if (original) Object.defineProperty(globalThis, 'sessionStorage', original);
    else delete globalThis.sessionStorage;
    store.getState().reset();
  }
});
