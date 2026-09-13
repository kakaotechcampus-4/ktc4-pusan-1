/**
 * 질문 시점 타임라인. 마커를 누르면 그 시점으로 이동한다.
 */

import { fmt } from '../../lib/format';
import type { Moment } from '../../types/interview';

/** 트랙 양끝 6% 여백 — 첫 · 마지막 마커 라벨이 카드 밖으로 나가지 않게 한다. */
const pct = (sec: number, total: number) =>
  `${(6 + (Math.min(sec, total) / Math.max(total, 1)) * 88).toFixed(1)}%`;

export interface TimelineProps {
  moments: Moment[];
  durationSec: number;
  activeId: string | null;
  onSelect: (moment: Moment) => void;
}

export function Timeline({ moments, durationSec, activeId, onSelect }: TimelineProps) {
  const active = moments.find((m) => m.id === activeId);

  return (
    <div className="overflow-x-auto rounded-xl bg-white/[0.06] px-6 pt-4 pb-3">
      <div className="relative h-[92px] min-w-[560px]">
        <div className="absolute inset-x-0 top-[34px] h-1.5 rounded-full bg-white/10" />
        {active && (
          <div
            className="absolute top-[34px] left-0 h-1.5 rounded-full bg-[#2B44D6] transition-[width] duration-200"
            style={{ width: pct(active.atSec, durationSec) }}
          />
        )}

        {moments.map((m, i) => {
          const on = m.id === activeId;
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => onSelect(m)}
              aria-pressed={on}
              aria-label={`${fmt(m.atSec)} ${m.label}`}
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1.5"
              style={{ left: pct(m.atSec, durationSec) }}
            >
              <span
                className={`block h-[18px] font-mono text-[12px] leading-[18px] ${
                  on ? 'text-[#7A97FF]' : 'text-white/45'
                }`}
              >
                {fmt(m.atSec)}
              </span>
              {/* 고정 26px 슬롯 안에서 원을 가운데 둔다 — 크기가 달라도 트랙 중심에 놓인다 */}
              <span className="flex h-[26px] items-center justify-center">
                <span
                  className={`box-border block rounded-full border-[3px] transition-all ${
                    on
                      ? 'h-[22px] w-[22px] border-[#2B44D6] bg-[#2B44D6]'
                      : 'h-4 w-4 border-white/30 bg-[#0B0E14] hover:border-white/60'
                  }`}
                />
              </span>
              <span
                className={`px-1 text-[13px] font-medium whitespace-nowrap ${
                  on ? 'text-white' : 'text-white/50'
                }`}
                // 이웃한 마커의 라벨이 겹치지 않도록 한 칸씩 엇갈려 내린다.
                style={{ marginTop: i % 2 ? 20 : 2 }}
              >
                {m.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
