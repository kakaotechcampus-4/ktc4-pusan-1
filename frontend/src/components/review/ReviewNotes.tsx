/**
 * 면접관 메모 (#137 1-3).
 *
 * 저장은 `useMemoAutosave` 가 한다 — 면접 중 화면의 메모(#219)와 같은 칸을 쓰므로
 * 규칙을 두 군데에 두지 않는다.
 * AI 결과와 상관없이 쓸 수 있다. 요약이 FAILED 여도 이 칸은 살아 있다.
 * 검토 상태는 화면 아래 막대가 맡는다 (`ReviewStatusBar`).
 */

import { MEMO_MAX, useMemoAutosave } from '../../hooks/useMemoAutosave';
import type { ReviewUpdateResponse } from '../../types/interview';

export interface ReviewNotesProps {
  interviewId: string;
  memo: string;
  /** 저장이 끝나면 상세 캐시에 반영한다 */
  onSaved: (saved: ReviewUpdateResponse) => void;
}

export function ReviewNotes({ interviewId, memo: savedMemo, onSaved }: ReviewNotesProps) {
  const {
    memo,
    setMemo,
    state: memoState,
  } = useMemoAutosave({ interviewId, initial: savedMemo, onSaved });

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
        onChange={(e) => setMemo(e.target.value)}
        placeholder="확인한 근거와 다음에 물어볼 것을 적어 두세요. 입력하면 자동으로 저장됩니다."
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand/20 mt-3 w-full resize-y rounded-xl border p-3.5 text-[15px] leading-relaxed transition outline-none focus:ring-4"
      />
      <p className="text-ink-dim mt-1.5 text-right font-mono text-[12px]">
        {memo.length}/{MEMO_MAX}
      </p>
    </section>
  );
}
