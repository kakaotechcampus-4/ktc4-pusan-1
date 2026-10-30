import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { getInterview } from '../../api/interview';
import { MEMO_MAX, useMemoAutosave } from '../../hooks/useMemoAutosave';

export function LiveMemoPanel({ interviewId }: { interviewId: string | null }) {
  const owner = useQuery({
    queryKey: ['interview', interviewId],
    queryFn: () => getInterview(interviewId!),
    enabled: Boolean(interviewId),
  });
  const { memo, setMemo, state, flush, hydrated } = useMemoAutosave({
    interviewId,
    initial: owner.data?.memo,
  });
  const [open, setOpen] = useState(() => window.matchMedia('(min-width: 768px)').matches);
  const input = useRef<HTMLTextAreaElement>(null);
  const ready = owner.data?.memo !== undefined && hydrated;
  useEffect(() => {
    if (ready && open && window.matchMedia('(min-width: 768px)').matches)
      input.current?.focus({ preventScroll: true });
  }, [interviewId, ready, open]);
  return (
    <section className="glass interview-readable flex max-h-[45%] min-h-11 shrink-0 flex-col overflow-hidden rounded-2xl">
      <header className="flex min-h-11 shrink-0 items-center gap-2 px-3">
        <button
          type="button"
          onClick={() => setOpen((old) => !old)}
          aria-expanded={open}
          className="text-ink flex-1 py-2 text-left text-sm font-semibold"
        >
          메모 · {open ? '접기' : '펼치기'}
        </button>
        <span role="status" className="text-ink-muted text-xs">
          {state === 'saving'
            ? '저장 중'
            : state === 'saved'
              ? '저장됨'
              : state === 'failed'
                ? '저장 실패'
                : ready
                  ? ''
                  : '불러오는 중'}
        </span>
      </header>
      {open && (
        <div className="flex min-h-0 flex-col px-3 pb-3">
          <textarea
            ref={input}
            data-live-memo="true"
            aria-label="면접 중 메모"
            rows={3}
            maxLength={MEMO_MAX}
            disabled={!ready}
            value={memo}
            onChange={(event) => setMemo(event.target.value)}
            onBlur={() => void flush()}
            placeholder="면접 중 메모"
            className="text-ink border-border-base min-h-10 w-full flex-1 resize-none rounded-xl border bg-white/5 p-2 text-[15px] leading-relaxed disabled:opacity-50"
          />
          {(owner.isError || (owner.data && owner.data.memo === undefined)) && (
            <p role="alert" className="text-warning mt-1 text-xs">
              메모를 읽지 못했습니다.{' '}
              <button type="button" onClick={() => void owner.refetch()} className="underline">
                다시 확인
              </button>
            </p>
          )}
          {state === 'failed' && (
            <button
              type="button"
              onClick={() => void flush()}
              className="text-warning mt-1 text-left text-xs underline"
            >
              입력은 보관 중입니다. 다시 저장
            </button>
          )}
        </div>
      )}
    </section>
  );
}
