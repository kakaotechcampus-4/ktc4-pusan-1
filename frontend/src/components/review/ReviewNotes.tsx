/**
 * 검토 상태와 면접관 메모 (#137 1-3).
 *
 * 메모는 입력이 멈추면 저장한다. 화면을 나갈 때 남은 입력도 보낸다 — 「저장」 버튼이
 * 없으니 마지막 몇 글자가 사라지면 면접관은 알아챌 방법이 없다.
 * 상태와 메모는 AI 결과와 상관없이 쓸 수 있다. 요약이 FAILED 여도 이 칸은 살아 있다.
 */

import { useEffect, useRef, useState } from 'react';
import { updateReview } from '../../api/review';
import type { ReviewStatus, ReviewUpdateResponse } from '../../types/interview';

/** 입력이 이만큼 멈추면 저장한다 */
const SAVE_DELAY_MS = 800;
/** 서버 상한(`ReviewUpdateRequest.memo`)과 같다 */
const MEMO_MAX = 4000;

const STATUSES: { id: ReviewStatus; label: string }[] = [
  { id: 'PENDING', label: '검토 대기' },
  { id: 'IN_REVIEW', label: '검토 중' },
  { id: 'CONFIRMED', label: '확정' },
];

type SaveState = 'idle' | 'saving' | 'saved' | 'failed';

export interface ReviewNotesProps {
  interviewId: string;
  reviewStatus: ReviewStatus;
  reviewedAt: string | null;
  memo: string;
  /** 저장이 끝나면 상세 캐시에 반영한다 */
  onSaved: (saved: ReviewUpdateResponse) => void;
}

export function ReviewNotes({
  interviewId,
  reviewStatus,
  reviewedAt,
  memo: savedMemo,
  onSaved,
}: ReviewNotesProps) {
  const [memo, setMemo] = useState(savedMemo);
  const [memoState, setMemoState] = useState<SaveState>('idle');
  const [statusError, setStatusError] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);

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

  const changeStatus = (next: ReviewStatus) => {
    if (next === reviewStatus || statusSaving) return;
    setStatusSaving(true);
    setStatusError(false);
    updateReview(interviewId, { reviewStatus: next })
      .then((saved) => onSavedRef.current({ ...saved, memo: pending.current ?? saved.memo }))
      .catch(() => setStatusError(true))
      .finally(() => setStatusSaving(false));
  };

  return (
    <section className="border-border-base bg-surface-panel rounded-2xl border p-4 sm:p-5">
      <div className="border-border-base flex flex-wrap items-center gap-3 border-b pb-4">
        <h2 className="text-ink text-[15px] font-semibold">검토</h2>
        <span className="flex-1" />
        <div role="radiogroup" aria-label="검토 상태" className="flex gap-1.5">
          {STATUSES.map((s) => {
            const on = s.id === reviewStatus;
            return (
              <button
                key={s.id}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={statusSaving}
                onClick={() => changeStatus(s.id)}
                className={`rounded-lg border px-3 py-1.5 text-[13px] transition disabled:opacity-60 ${
                  on
                    ? 'border-brand bg-brand/15 text-brand-soft'
                    : 'border-border-base bg-surface-bright text-ink-muted hover:text-ink'
                }`}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>

      <p aria-live="polite" className="text-ink-dim mt-2 min-h-[18px] text-[12px]">
        {statusError
          ? '상태를 바꾸지 못했습니다. 다시 눌러주세요.'
          : reviewStatus === 'CONFIRMED' && reviewedAt
            ? `${new Date(reviewedAt).toLocaleString('ko-KR')} 확정`
            : ''}
      </p>

      <label htmlFor="review-memo" className="text-ink-muted mt-2 block text-[13px]">
        면접관 메모
      </label>
      <textarea
        id="review-memo"
        rows={5}
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
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim mt-2 w-full resize-y rounded-lg border p-3 text-[15px] leading-relaxed"
      />
      <p aria-live="polite" className="mt-1.5 flex text-[12px]">
        <span className={memoState === 'failed' ? 'text-[#FFC46B]' : 'text-ink-dim'}>
          {memoState === 'saving' && '저장 중…'}
          {memoState === 'saved' && '저장됨'}
          {memoState === 'failed' && '저장하지 못했습니다. 계속 입력하면 다시 시도합니다.'}
        </span>
        <span className="flex-1" />
        <span className="text-ink-dim font-mono">
          {memo.length}/{MEMO_MAX}
        </span>
      </p>
    </section>
  );
}
