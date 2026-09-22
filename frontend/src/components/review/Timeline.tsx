/**
 * 질문 시점 타임라인. 마커를 누르면 그 시점으로 이동한다.
 *
 * 시안처럼 위에 눈금자를 두고 그 아래에 Q 마커를 늘어놓는다. 눈금자가 시각을 읽어주므로
 * 마커마다 시각을 적지 않는다 — 고른 질문의 시각은 재생 영역과 아래 목록에 나온다.
 */

import { fmt } from '../../lib/format';
import type { Moment } from '../../types/interview';

/** 트랙 양끝 6% 여백 — 첫 · 마지막 마커 라벨이 카드 밖으로 나가지 않게 한다. */
const pct = (sec: number, total: number) =>
  `${(6 + (Math.min(sec, total) / Math.max(total, 1)) * 88).toFixed(1)}%`;

/** 눈금 간격 후보. 사람이 읽기 좋은 값만 둔다. */
const STEPS = [30, 60, 120, 300, 600, 900, 1800, 3600];

/** 눈금자에 찍을 시각들. 칸이 여섯을 넘지 않는 가장 촘촘한 간격을 고른다. */
function ruler(total: number) {
  const step = STEPS.find((s) => total / s <= 6) ?? STEPS[STEPS.length - 1];
  const marks: number[] = [];
  for (let t = 0; t <= total; t += step) marks.push(t);
  return marks;
}

export interface TimelineProps {
  moments: Moment[];
  durationSec: number;
  activeId: string | null;
  onSelect: (moment: Moment) => void;
}

export function Timeline({ moments, durationSec, activeId, onSelect }: TimelineProps) {
  const active = moments.find((m) => m.id === activeId);

  return (
    <section className="border-border-base bg-surface-panel rounded-2xl border p-4 sm:p-5">
      <div className="overflow-x-auto">
        <div className="relative min-w-[560px]">
          <div className="border-border-base relative h-[18px] border-b">
            {ruler(durationSec).map((t) => (
              <span
                key={t}
                className="text-ink-dim absolute top-0 -translate-x-1/2 font-mono text-[11px] leading-[18px]"
                style={{ left: pct(t, durationSec) }}
              >
                {fmt(t)}
              </span>
            ))}
          </div>

          {/* 고른 질문의 위치를 세로선으로 짚어 준다. */}
          {active && (
            <div
              aria-hidden
              className="bg-brand/60 absolute top-[18px] bottom-0 w-px transition-[left] duration-200"
              style={{ left: pct(active.atSec, durationSec) }}
            />
          )}

          <div className="relative mt-3 h-[72px]">
            {moments.map((m, i) => {
              const on = m.id === activeId;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => onSelect(m)}
                  aria-pressed={on}
                  aria-label={`${fmt(m.atSec)} ${m.label}`}
                  className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1"
                  style={{ left: pct(m.atSec, durationSec) }}
                >
                  <span
                    className={`rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold transition ${
                      on
                        ? 'border-brand bg-brand text-white'
                        : 'border-border-base bg-surface-bright text-ink-muted hover:border-ink-dim hover:text-ink border-dashed'
                    }`}
                  >
                    Q{i + 1}
                  </span>
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[11px] whitespace-nowrap transition ${
                      on
                        ? 'border-brand/40 bg-brand/15 text-ink'
                        : 'text-ink-dim border-transparent'
                    }`}
                    // 이웃한 마커의 라벨이 겹치지 않도록 한 칸씩 엇갈려 내린다.
                    style={{ marginTop: i % 2 ? 16 : 0 }}
                  >
                    {m.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <p className="text-ink-dim mt-2 text-[12px]">마커를 누르면 영상이 그 시점부터 재생됩니다.</p>
    </section>
  );
}
