import type { Suggestion } from '../types/interview';

export const UNPINNED_SUGGESTION_LIMIT = 5;

/** 같은 시각이면 나중에 받은 질문을 먼저 보여준다. 원본과 고정 상태는 보존한다. */
export function visibleSuggestions(suggestions: readonly Suggestion[]): Suggestion[] {
  const latest = suggestions
    .map((suggestion, index) => ({ suggestion, index }))
    .sort(
      (a, b) =>
        Date.parse(b.suggestion.createdAt) - Date.parse(a.suggestion.createdAt) ||
        b.index - a.index,
    )
    .map(({ suggestion }) => suggestion);
  return [
    ...latest.filter((suggestion) => suggestion.pinned),
    ...latest.filter((suggestion) => !suggestion.pinned).slice(0, UNPINNED_SUGGESTION_LIMIT),
  ];
}
