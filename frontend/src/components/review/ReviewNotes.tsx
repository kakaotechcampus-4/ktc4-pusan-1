/**
 * 면접관 메모 (#137 1-3).
 *
 * 메모는 입력이 멈추면 저장한다. 화면을 나갈 때 남은 입력도 보낸다 — 「저장」 버튼이
 * 없으니 마지막 몇 글자가 사라지면 면접관은 알아챌 방법이 없다.
 * AI 결과와 상관없이 쓸 수 있다. 요약이 FAILED 여도 이 칸은 살아 있다.
 * 검토 상태는 화면 아래 막대가 맡는다 (`ReviewStatusBar`).
 */

import { useEffect, useRef, useState } from 'react';
import { updateReview } from '../../api/review';
import type { ReviewUpdateResponse } from '../../types/interview';

/** 입력이 이만큼 멈추면 저장한다 */
const SAVE_DELAY_MS = 800;
/** 서버 상한(`ReviewUpdateRequest.memo`)과 같다 */
const MEMO_MAX = 4000;

type SaveState = 'idle' | 'saving' | 'saved' | 'failed';

export interface ReviewNotesProps {
  interviewId: string;
  memo: string;
  /** 저장이 끝나면 상세 캐시에 반영한다 */
  onSaved: (saved: ReviewUpdateResponse) => void;
}

export function ReviewNotes({ interviewId, memo: savedMemo, onSaved }: ReviewNotesProps) {
  const [memo, setMemo] = useState(savedMemo);
  const [memoState, setMemoState] = useState<SaveState>('idle');

  // 나갈 때 보낼 값. effect 정리 함수는 그 시점의 state 를 못 읽으므로 ref 로 둔다.
  const pending = useRef<string | null>(null);
  // 부모가 다시 그릴 때마다 새 함수가 온다. 의존성에 넣으면 저장 타이머가 계속 밀린다.
  const onSavedRef = useRef(onSaved);
  useEffect(() => {
    onSavedRef.current = onSaved;
  });

  useEffect(() => {
    if (pending.current === null) return;
    const value = pending.current;
    const timer = setTimeout(() => {
      setMemoState('saving');
      updateReview(interviewId, { memo: value })
        .then((saved) => {
          // 저장하는 사이 더 입력했으면 그 입력이 다음 저장을 기다리고 있다.
          if (pending.current === value) pending.current = null;
          setMemoState('saved');
          onSavedRef.current(saved);
        })
        .catch(() => setMemoState('failed'));
    }, SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [interviewId, memo]);

  useEffect(
    () => () => {
      // 키보드에서 손을 떼자마자 나가도 남은 입력을 버리지 않는다.
      if (pending.current !== null) void updateReview(interviewId, { memo: pending.current });
    },
    [interviewId],
  );

  return (
    <section className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-5">
      <div className="flex items-center gap-2">
        <h2 className="text-ink text-[16px] font-semibold">
          <label htmlFor="review-memo">면접관 메모</label>
        </h2>
        <span className="flex-1" />
        <span
          aria-live="polite"
          className={`text-[12px] ${memoState === 'failed' ? 'text-danger' : 'text-ink-dim'}`}
        >
          {memoState === 'saving' && '저장 중…'}
          {memoState === 'saved' && '저장됨'}
          {memoState === 'failed' && '저장하지 못했습니다. 계속 입력하면 다시 시도합니다.'}
        </span>
      </div>
      <textarea
        id="review-memo"
        rows={6}
        maxLength={MEMO_MAX}
        value={memo}
        onChange={(e) => {
          // NUL 은 서버가 422 로 막는다. 붙여넣기로 섞여 들어와도 저장이 막히지 않게 뺀다.
          const value = e.target.value.replaceAll('\0', '');
          pending.current = value;
          setMemo(value);
          setMemoState('idle');
        }}
        placeholder="확인한 근거와 다음에 물어볼 것을 적어 두세요. 입력하면 자동으로 저장됩니다."
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand/20 mt-3 w-full resize-y rounded-xl border p-3.5 text-[15px] leading-relaxed transition outline-none focus:ring-4"
      />
      <p className="text-ink-dim mt-1.5 text-right font-mono text-[12px]">
        {memo.length}/{MEMO_MAX}
      </p>
    </section>
  );
}
