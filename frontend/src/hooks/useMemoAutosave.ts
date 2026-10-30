/**
 * 면접관 메모 자동 저장 (#137 1-3 · #219).
 *
 * 「저장」 버튼이 없다. 입력이 멈추면 보내고, 화면을 나갈 때 남은 입력도 보낸다 —
 * 마지막 몇 글자가 사라지면 면접관은 알아챌 방법이 없다.
 *
 * 면접 중 화면과 면접 기록 화면이 같은 칸(`PATCH /interviews/{interviewId}` 의 `memo`)을
 * 쓴다. 저장 규칙을 두 군데에 따로 두면 한쪽이 상대가 저장한 글을 덮으므로 여기 하나만 둔다.
 *
 * `interviewId` 는 늦게 올 수 있다 — 면접 중 화면은 방에 붙어 상태를 조회한 뒤에야 안다.
 * 그동안 입력은 받아 두고, 아이디가 오면 그때 보낸다. 입력부터 되는 것이 중요하다.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { updateReview } from '../api/review';
import type { ReviewUpdateResponse } from '../types/interview';

/** 입력이 이만큼 멈추면 저장한다 */
const SAVE_DELAY_MS = 800;
/** 서버 상한(`ReviewUpdateRequest.memo`)과 같다 */
export const MEMO_MAX = 4000;

export type MemoSaveState = 'idle' | 'saving' | 'saved' | 'failed';

export interface UseMemoAutosaveOptions {
  /** 저장할 면접. 아직 모르면 null — 입력은 받고 저장만 기다린다 */
  interviewId: string | null;
  /** 서버에 들어 있는 값. 모르면 빈 칸에서 시작한다 */
  initial?: string;
  /** 저장이 끝나면 호출한다. 조회 캐시를 맞추는 데 쓴다 */
  onSaved?: (saved: ReviewUpdateResponse) => void;
}

export function useMemoAutosave({ interviewId, initial = '', onSaved }: UseMemoAutosaveOptions) {
  const [memo, setValue] = useState(initial);
  const [state, setState] = useState<MemoSaveState>('idle');

  // 나갈 때 보낼 값. effect 정리 함수는 그 시점의 state 를 못 읽으므로 ref 로 둔다.
  const pending = useRef<string | null>(null);
  // 부모가 다시 그릴 때마다 새 함수가 온다. 의존성에 넣으면 저장 타이머가 계속 밀린다.
  const onSavedRef = useRef(onSaved);
  useEffect(() => {
    onSavedRef.current = onSaved;
  });

  const setMemo = useCallback((value: string) => {
    // NUL 은 서버가 422 로 막는다. 붙여넣기로 섞여 들어와도 저장이 막히지 않게 뺀다.
    const clean = value.replaceAll('\0', '');
    pending.current = clean;
    setValue(clean);
    setState('idle');
  }, []);

  useEffect(() => {
    if (interviewId === null || pending.current === null) return;
    const value = pending.current;
    const timer = setTimeout(() => {
      setState('saving');
      updateReview(interviewId, { memo: value })
        .then((saved) => {
          // 저장하는 사이 더 입력했으면 그 입력이 다음 저장을 기다리고 있다.
          if (pending.current === value) pending.current = null;
          setState('saved');
          onSavedRef.current?.(saved);
        })
        .catch(() => setState('failed'));
    }, SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [interviewId, memo]);

  useEffect(
    () => () => {
      // 키보드에서 손을 떼자마자 나가도 남은 입력을 버리지 않는다.
      if (interviewId !== null && pending.current !== null) {
        void updateReview(interviewId, { memo: pending.current });
      }
    },
    [interviewId],
  );

  return { memo, setMemo, state };
}
