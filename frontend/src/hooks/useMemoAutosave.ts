import { useEffect, useRef, useSyncExternalStore } from 'react';
import { updateReview } from '../api/review';
import { getInterview } from '../api/interview';
import { readAccessToken } from '../lib/authToken';
import { createMemoQueue } from '../lib/memoQueue';
import { clearMemoDrafts } from '../lib/memoDraft';
import { queryClient } from '../lib/queryClient';
import type { Review, ReviewUpdateResponse } from '../types/interview';

export const MEMO_MAX = 4000;
export type { MemoSaveState } from '../lib/memoQueue';
const queue = createMemoQueue(async (id, memo, expectedMemo) => {
  const token = readAccessToken();
  const saved = await updateReview(id, { memo, expectedMemo });
  if (readAccessToken() !== token) return saved;
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
export const flushMemosForRead = (ids: readonly string[]) => queue.flushForRead(ids);
const EMPTY = {
  memo: '',
  state: 'idle' as const,
  version: 0,
  saved: 0,
  hydrated: false,
  baseline: '',
  serverMemo: undefined as string | undefined,
  result: undefined as ReviewUpdateResponse | undefined,
};

if (typeof window !== 'undefined') {
  const clear = () => {
    queue.clear();
    clearMemoDrafts();
  };
  window.addEventListener('irya:token-changed', clear);
  window.addEventListener('storage', (event) => {
    if (event.key === 'accessToken' || event.key === null) clear();
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
  const notified = useRef<string | null>(null);
  useEffect(() => {
    callback.current = onSaved;
  });
  useEffect(() => {
    const key = `${interviewId}:${draft.saved}`;
    if (draft.state === 'saved' && draft.result && notified.current !== key) {
      notified.current = key;
      callback.current?.(draft.result);
    }
  }, [interviewId, draft.state, draft.saved, draft.result]);
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
    serverMemo: draft.serverMemo,
    readConflict: async () => {
      if (!interviewId) return;
      const token = readAccessToken();
      const current = await getInterview(interviewId);
      if (typeof current.memo !== 'string') throw new Error('메모를 읽지 못했습니다.');
      if (token === readAccessToken()) queue.reviewConflict(interviewId, current.memo);
    },
    reapply: () => (interviewId ? queue.reapply(interviewId) : Promise.resolve()),
    memo: draft.memo,
    hydrated: draft.hydrated,
    state: draft.state,
    setMemo: (value: string) => {
      if (interviewId) queue.edit(interviewId, value);
    },
    flush: () => (interviewId ? queue.flush(interviewId) : Promise.resolve()),
  };
}
