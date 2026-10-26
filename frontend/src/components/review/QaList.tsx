/**
 * 전체 질문과 답변. 항목을 누르면 그 시점으로 이동하고, 별표로 북마크한다.
 */

import { fmt } from '../../lib/format';
import type { Moment } from '../../types/interview';

export interface QaListProps {
  moments: Moment[];
  activeId: string | null;
  onSelect: (moment: Moment) => void;
  onBookmark: (moment: Moment) => void;
  open: boolean;
  onToggle: () => void;
}

export function QaList({ moments, activeId, onSelect, onBookmark, open, onToggle }: QaListProps) {
  return (
    <section className="border-border-base bg-surface-panel rounded-2xl border p-4 sm:p-5">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="qa-list"
        className={`flex w-full items-center gap-3 text-left ${open ? 'border-border-base border-b pb-4' : ''}`}
      >
        <span className="text-ink text-[15px] font-semibold">질문 · 답변</span>
        <span className="bg-surface-bright text-ink-muted rounded-full px-2 py-0.5 font-mono text-[12px]">
          {moments.length}
        </span>
        <span className="flex-1" />
        <span className="text-ink-muted flex items-center gap-1 text-[13px]">
          {open ? '접기' : '펼치기'}
          <span aria-hidden className="material-symbols-outlined text-[18px]">
            {open ? 'expand_less' : 'expand_more'}
          </span>
        </span>
      </button>

      {open && (
        <div id="qa-list" className="mt-4 flex flex-col gap-3">
          {moments.map((m, i) => {
            const on = m.id === activeId;
            return (
              // 북마크 버튼을 항목 버튼 안에 넣으면 버튼이 겹친다. 형제로 두고 위에 띄운다.
              <div key={m.id} className="relative">
                <button
                  type="button"
                  onClick={() => onSelect(m)}
                  aria-current={on}
                  className={`relative w-full overflow-hidden rounded-xl border py-4 pr-12 pl-6 text-left transition ${
                    on
                      ? 'border-brand/50 bg-surface-bright'
                      : 'border-border-base bg-surface-container hover:bg-surface-bright'
                  }`}
                >
                  {/* 고른 항목을 왼쪽 띠로 짚어 준다. */}
                  <span
                    aria-hidden
                    className={`absolute top-3 bottom-3 left-0 w-1 rounded-r ${on ? 'bg-brand' : 'bg-transparent'}`}
                  />
                  <span className="flex items-start gap-3.5">
                    <span className="flex shrink-0 items-center gap-2 pt-0.5">
                      <span className="text-ink-dim font-mono text-[12px]">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <span
                        className={`rounded-full border px-2.5 py-0.5 font-mono text-[12px] ${
                          on
                            ? 'border-brand bg-brand/15 text-brand-soft'
                            : 'border-border-base bg-surface-bright text-ink-muted'
                        }`}
                      >
                        {fmt(m.atSec)}
                      </span>
                    </span>
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="text-ink text-[15px] leading-snug font-semibold">
                        Q. {m.question}
                      </span>
                      <span className="text-ink-muted text-[13px] leading-relaxed">
                        A. {m.answer}
                      </span>
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onBookmark(m)}
                  aria-pressed={m.bookmarked}
                  aria-label={`${i + 1}번 문답 북마크`}
                  className={`absolute top-3 right-3 rounded-lg p-1.5 transition ${
                    m.bookmarked ? 'text-[#FFC46B]' : 'text-ink-dim hover:text-ink'
                  }`}
                >
                  <span
                    aria-hidden
                    className="material-symbols-outlined text-[20px]"
                    style={m.bookmarked ? { fontVariationSettings: "'FILL' 1" } : undefined}
                  >
                    star
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
