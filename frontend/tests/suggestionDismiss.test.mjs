import assert from 'node:assert/strict';
import { test } from 'node:test';
import { useInterviewStore } from '../src/stores/interviewStore.ts';
import { visibleSuggestions } from '../src/lib/visibleSuggestions.ts';

test('고정과 숨김은 재연결에 유지되고 취소·화면 초기화에 올바르게 복구된다', () => {
  const store = useInterviewStore;
  store.getState().reset();
  const questions = Array.from({ length: 7 }, (_, id) => ({
    id: String(id),
    content: '질문',
    createdAt: new Date(2026, 0, id + 1).toISOString(),
    pinned: false,
  }));
  store.getState().mergeSuggestions(questions);
  store.getState().toggleSuggestionPin('0');
  store.getState().dismissSuggestion('0');
  store.getState().dismissSuggestion('6');
  store.getState().mergeSuggestions(questions);
  let state = store.getState();
  assert.equal(state.suggestions.find((s) => s.id === '0').pinned, true);
  assert.deepEqual(
    visibleSuggestions(state.suggestions)
      .filter((s) => !state.hiddenSuggestionIds.includes(s.id))
      .map((s) => s.id),
    ['5', '4', '3', '2'],
  );
  store.getState().undoDismissSuggestion();
  assert.deepEqual(store.getState().hiddenSuggestionIds, ['0']);
  store.getState().reset();
  state = store.getState();
  assert.deepEqual(state.hiddenSuggestionIds, []);
  assert.deepEqual(state.suggestions, []);
});
