/**
 * 면접 기록 상세에 표시(채택 · 북마크)를 먼저 반영한다 (#137 1-4).
 *
 * 저장 응답을 기다리지 않고 화면을 바꾸고, 실패하면 이전 값으로 같은 함수를 다시
 * 부른다. 상세 전체를 되돌리지 않는 이유는 그사이 다른 항목을 눌렀을 수 있어서다.
 */

import type { MarkUpdate, Review } from '../types/interview';

export function applyMark<T extends Review>(review: T, itemId: string, mark: MarkUpdate): T {
  if ('state' in mark) {
    return {
      ...review,
      findings: review.findings.map((f) => (f.id === itemId ? { ...f, state: mark.state } : f)),
    };
  }
  return {
    ...review,
    moments: review.moments.map((m) =>
      m.id === itemId ? { ...m, bookmarked: mark.bookmarked } : m,
    ),
  };
}

/** `mark` 와 같은 종류의 지금 값 — 실패했을 때 되돌릴 표시. 없는 id 면 null */
export function currentMark(review: Review, itemId: string, mark: MarkUpdate): MarkUpdate | null {
  if ('state' in mark) {
    const f = review.findings.find((x) => x.id === itemId);
    return f ? { state: f.state } : null;
  }
  const m = review.moments.find((x) => x.id === itemId);
  return m ? { bookmarked: m.bookmarked } : null;
}
