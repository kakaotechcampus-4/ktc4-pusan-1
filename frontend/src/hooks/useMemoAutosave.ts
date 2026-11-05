import { useEffect, useRef, useSyncExternalStore } from 'react';
import { updateReview } from '../api/review';
import { getInterview } from '../api/interview';
import { readAccessToken } from '../lib/authToken';
import { createMemoQueue } from '../lib/memoQueue';
import { clearMemoDrafts, memoDraftKey, readMemoDraft, writeMemoDraft } from '../lib/memoDraft';
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
  ownerId,
  initial,
  onSaved,
}: {
  interviewId: string | null;
  ownerId?: string;
  initial?: string;
  onSaved?: (saved: ReviewUpdateResponse) => void;
}) {
  const draft = useSyncExternalStore(queue.subscribe, () =>
    interviewId ? queue.read(interviewId) : EMPTY,
  );
  const callback = useRef(onSaved);
  const notified = useRef<string | null>(null);
  const restored = useRef<string | null>(null);
  const draftKey = ownerId && interviewId ? memoDraftKey(ownerId, interviewId) : null;
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
    if (!interviewId || initial === undefined) return;
    queue.hydrate(interviewId, initial);
    if (draftKey && restored.current !== draftKey) {
      restored.current = draftKey;
      const stored = readMemoDraft(draftKey);
      if (stored) queue.restoreDraft(interviewId, stored.memo, stored.baseline);
    }
  }, [interviewId, initial, draftKey]);
  useEffect(() => {
    if (!interviewId || !draftKey || !draft.hydrated || restored.current !== draftKey) return;
    // 복구 직전 렌더의 값으로 복구된 초안을 덮지 않는다.
    if (queue.read(interviewId) !== draft) return;
    if (draft.version !== draft.saved) {
      const stored = readMemoDraft(draftKey);
      writeMemoDraft(draftKey, {
        memo: draft.memo,
        baseline:
          draft.state === 'conflict' && stored?.baseline === undefined ? undefined : draft.baseline,
      });
    } else if (readMemoDraft(draftKey)?.memo === draft.memo) writeMemoDraft(draftKey, null);
  }, [interviewId, draftKey, draft]);
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
    reapply: async () => {
      if (!interviewId) return;
      const token = readAccessToken();
      const current = await getInterview(interviewId);
      if (token !== readAccessToken()) throw new Error('로그인 상태가 바뀌었습니다.');
      if (typeof current.memo !== 'string') throw new Error('메모를 읽지 못했습니다.');
      queue.reviewConflict(interviewId, current.memo);
      await queue.reapply(interviewId);
      if (queue.read(interviewId).state !== 'saved') throw new Error('메모를 저장하지 못했습니다.');
    },
    memo: draft.memo,
    hydrated: draft.hydrated,
    state: draft.state,
    setMemo: (value: string) => {
      if (!interviewId) return;
      queue.edit(interviewId, value);
      if (draftKey) {
        const current = queue.read(interviewId);
        const stored = readMemoDraft(draftKey);
        writeMemoDraft(draftKey, {
          memo: current.memo,
          baseline:
            current.state === 'conflict' && stored?.baseline === undefined
              ? undefined
              : current.baseline,
        });
      }
    },
    flush: () => (interviewId ? queue.flush(interviewId) : Promise.resolve()),
  };
}
