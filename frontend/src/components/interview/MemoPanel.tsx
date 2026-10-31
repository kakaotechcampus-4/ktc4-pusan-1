import { MemoConflictNotice } from '../review/MemoConflictNotice';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { getInterview } from '../../api/interview';
import { memoDraftKey, readMemoDraft, writeMemoDraft } from '../../lib/memoDraft';
import { MEMO_MAX, useMemoAutosave } from '../../hooks/useMemoAutosave';

export function MemoPanel({ interviewId }: { interviewId: string | null }) {
  const owner = useQuery({
    queryKey: ['interview', interviewId],
    queryFn: () => getInterview(interviewId!),
    enabled: Boolean(interviewId),
  });
  const { memo, setMemo, state, flush, hydrated, serverMemo, readConflict, reapply } =
    useMemoAutosave({
      interviewId,
      initial: owner.data?.memo,
    });
  const [open, setOpen] = useState(() => window.matchMedia('(min-width: 768px)').matches);
  const input = useRef<HTMLTextAreaElement>(null);
  const restored = useRef<string | null>(null);
  const draftKey =
    owner.data && interviewId ? memoDraftKey(owner.data.interviewerId, interviewId) : null;
  const ready = owner.data?.memo !== undefined && hydrated;
  useEffect(() => {
    if (!ready || !draftKey) return;
    if (restored.current !== draftKey) {
      restored.current = draftKey;
      const draft = readMemoDraft(draftKey);
      if (draft !== null && draft !== owner.data?.memo) setMemo(draft);
      else if (draft !== null) writeMemoDraft(draftKey, null);
    } else if (state === 'saved' && readMemoDraft(draftKey) === memo) {
      writeMemoDraft(draftKey, null);
    }
  }, [ready, draftKey, owner.data?.memo, state, memo, setMemo]);
  useEffect(() => {
    if (ready && open && window.matchMedia('(min-width: 768px)').matches)
      input.current?.focus({ preventScroll: true });
  }, [interviewId, ready, open]);
  return (
    <section className="glass interview-readable flex max-h-[45%] min-h-11 shrink-0 flex-col overflow-hidden rounded-3xl">
      <header className="flex min-h-11 shrink-0 items-center gap-2 px-4">
        <button
          type="button"
          onClick={() => setOpen((old) => !old)}
          aria-expanded={open}
          className="text-ink flex-1 py-2 text-left text-[15px] font-semibold"
        >
          메모 · {open ? '접기' : '펼치기'}
        </button>
        <span
          role="status"
          className={`text-[12px] ${state === 'failed' || state === 'conflict' ? 'text-danger' : 'text-ink-dim'}`}
        >
          {state === 'saving'
            ? '저장 중'
            : state === 'saved'
              ? '저장됨'
              : state === 'conflict'
                ? '다른 창에서 변경됨'
                : state === 'failed'
                  ? '저장 실패'
                  : ready
                    ? ''
                    : '불러오는 중'}
        </span>
      </header>
      {open && (
        <div className="flex min-h-0 flex-col px-4 pb-3">
          <textarea
            ref={input}
            data-live-memo="true"
            aria-label="면접 중 메모"
            rows={3}
            maxLength={MEMO_MAX}
            disabled={!ready}
            value={memo}
            onChange={(event) => {
              const value = event.target.value.replaceAll('\0', '').slice(0, MEMO_MAX);
              if (draftKey) writeMemoDraft(draftKey, value);
              setMemo(value);
            }}
            onBlur={() => void flush()}
            placeholder="면접 중 메모"
            className="text-ink placeholder:text-ink-dim min-h-10 w-full flex-1 resize-none bg-transparent text-[15px] leading-relaxed disabled:opacity-50"
          />
          {(owner.isError || (owner.data && owner.data.memo === undefined)) && (
            <p role="alert" className="text-warning mt-1 text-xs">
              메모를 읽지 못했습니다.{' '}
              <button type="button" onClick={() => void owner.refetch()} className="underline">
                다시 확인
              </button>
            </p>
          )}
          {state === 'conflict' && (
            <MemoConflictNotice
              serverMemo={serverMemo}
              readConflict={readConflict}
              reapply={reapply}
            />
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
