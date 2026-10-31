import { MemoConflictNotice } from './MemoConflictNotice';
import { useId } from 'react';
import { MEMO_MAX, useMemoAutosave } from '../../hooks/useMemoAutosave';
import type { ReviewUpdateResponse } from '../../types/interview';

export interface ReviewNotesProps {
  interviewId: string;
  memo: string;
  onSaved?: (saved: ReviewUpdateResponse) => void;
}

export function ReviewNotes({ interviewId, memo: initial, onSaved }: ReviewNotesProps) {
  const id = useId();
  const { memo, setMemo, state, flush, serverMemo, readConflict, reapply } = useMemoAutosave({
    interviewId,
    initial,
    onSaved,
  });
  return (
    <section className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-5">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-ink text-[16px] font-semibold">
          면접관 메모
        </label>
        <span
          role="status"
          className={`text-xs ${state === 'failed' || state === 'conflict' ? 'text-danger' : 'text-ink-dim'}`}
        >
          {state === 'saving'
            ? '저장 중'
            : state === 'saved'
              ? '저장됨'
              : state === 'conflict'
                ? '다른 창에서 변경됨'
                : state === 'failed'
                  ? '저장 실패'
                  : ''}
        </span>
      </div>
      <textarea
        id={id}
        rows={4}
        maxLength={MEMO_MAX}
        value={memo}
        onChange={(event) => setMemo(event.target.value)}
        onBlur={() => void flush()}
        placeholder="확인한 내용과 다음에 물어볼 것을 적어 두세요."
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand focus:ring-brand/20 mt-3 w-full resize-y rounded-xl border p-3.5 text-[15px] leading-relaxed transition outline-none focus:ring-4"
      />
      {state === 'conflict' && (
        <MemoConflictNotice serverMemo={serverMemo} readConflict={readConflict} reapply={reapply} />
      )}
      <div className="text-ink-dim mt-1 flex justify-between text-xs">
        <span>
          {state === 'failed' && (
            <button type="button" className="text-brand underline" onClick={() => void flush()}>
              다시 저장
            </button>
          )}
        </span>
        <span>
          {memo.length}/{MEMO_MAX}
        </span>
      </div>
    </section>
  );
}
