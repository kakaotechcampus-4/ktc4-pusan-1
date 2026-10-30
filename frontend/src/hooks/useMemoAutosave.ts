import { useEffect, useRef, useSyncExternalStore } from 'react';
import { updateReview } from '../api/review';
import { createMemoQueue } from '../lib/memoQueue';
import { queryClient } from '../lib/queryClient';
import type { Review, ReviewUpdateResponse } from '../types/interview';

export const MEMO_MAX = 4000;
export type { MemoSaveState } from '../lib/memoQueue';
const queue = createMemoQueue(async (id, memo) => {
  const saved = await updateReview(id, { memo });
  queryClient.setQueryData(
    ['interview', id],
    (old: object | undefined) => old && { ...old, ...saved },
  );
  queryClient.setQueryData(
    ['review', id],
    (old: Review | undefined) => old && { ...old, memo: saved.memo },
  );
  void queryClient.invalidateQueries({ queryKey: ['interviews'] });
  return saved;
});
const EMPTY = { memo: '', state: 'idle' as const, version: 0, saved: 0, hydrated: false };

if (typeof window !== 'undefined') {
  window.addEventListener('irya:token-changed', () => queue.clear());
  window.addEventListener('storage', (event) => {
    if (event.key === 'accessToken' || event.key === null) queue.clear();
  });
}

export function useMemoAutosave({
  interviewId,
  initial,
  onSaved,
}: {
  interviewId: string | null;
  initial?: string;
  onSaved?: (saved: ReviewUpdateResponse) => void;
}) {
  const draft = useSyncExternalStore(queue.subscribe, () =>
    interviewId ? queue.read(interviewId) : EMPTY,
  );
  const callback = useRef(onSaved);
  useEffect(() => {
    callback.current = onSaved;
  });
  useEffect(() => {
    if (interviewId && initial !== undefined) queue.hydrate(interviewId, initial);
  }, [interviewId, initial]);
  useEffect(
    () => () => {
      if (interviewId) void queue.flush(interviewId);
    },
    [interviewId],
  );
  return {
    memo: draft.memo,
    state: draft.state,
    setMemo: (value: string) => {
      if (interviewId) queue.edit(interviewId, value);
    },
    flush: () => (interviewId ? queue.flush(interviewId) : Promise.resolve()),
  };
}
