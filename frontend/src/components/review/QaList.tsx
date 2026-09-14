/**
 * 전체 질문과 답변. 항목을 누르면 그 시점으로 이동한다.
 */

import { fmt } from '../../lib/format';
import type { Moment } from '../../types/interview';

export interface QaListProps {
  moments: Moment[];
  activeId: string | null;
  onSelect: (moment: Moment) => void;
  open: boolean;
  onToggle: () => void;
}

export function QaList({ moments, activeId, onSelect, open, onToggle }: QaListProps) {
  return (
    <section>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="qa-list"
        className="flex w-full items-center gap-3 rounded-xl bg-white/[0.06] px-5 py-4 text-left transition hover:bg-white/[0.09]"
      >
        <span className="text-[15px] font-semibold text-white">전체 질문과 답변</span>
        <span className="font-mono text-[13px] text-white/45">{moments.length}개</span>
        <span className="flex-1" />
        <span className="text-[13px] text-white/50">{open ? '접기 ▴' : '펼치기 ▾'}</span>
      </button>

      {open && (
        <div id="qa-list" className="mt-2 flex flex-col gap-2">
          {moments.map((m) => {
            const on = m.id === activeId;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => onSelect(m)}
                aria-current={on}
                className={`grid grid-cols-[56px_minmax(0,1fr)] gap-4 rounded-xl border-l-[3px] bg-white/[0.06] px-5 py-4 text-left transition hover:bg-white/[0.09] ${
                  on ? 'border-l-[#2B44D6]' : 'border-l-transparent'
                }`}
              >
                <span
                  className={`pt-0.5 font-mono text-[13px] ${on ? 'text-[#7A97FF]' : 'text-white/45'}`}
                >
                  {fmt(m.atSec)}
                </span>
                <span className="flex min-w-0 flex-col gap-1.5">
                  <span className="text-[15px] leading-normal font-semibold text-white">
                    {m.question}
                  </span>
                  <span className="text-[14px] leading-relaxed text-white/60">{m.answer}</span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
