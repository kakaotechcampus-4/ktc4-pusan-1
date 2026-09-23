/**
 * 지금 누가 말하는지 — 이름 · 파형 · "말하는 중".
 *
 * 시안의 LIVE SCRIPT 헤더에 있던 표시지만 여기서는 상단 바에 둔다.
 * 전사 패널은 면접관에게만 보이는데, 화자 표시는 지원자에게도 필요하기 때문이다.
 */

import { useInterviewStore } from '../../stores/interviewStore';
import { SPEAKER_STYLE } from './speakerStyle';

/** 파형 막대의 시작 지연. 같은 높이로 함께 뛰지 않도록 어긋나게 둔다. */
const BAR_DELAYS = [0, 0.15, 0.07, 0.25];

export function SpeakerBadge() {
  const speakingNow = useInterviewStore((s) => s.speakingNow);
  if (!speakingNow) return null;
  const st = SPEAKER_STYLE[speakingNow];

  return (
    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1.5">
      <span className={`text-[13px] font-semibold whitespace-nowrap ${st.text}`}>{st.label}</span>
      <span className="flex h-3.5 items-end gap-[2px]">
        {BAR_DELAYS.map((d) => (
          <span
            key={d}
            className={`w-[2px] rounded-full ${st.bar} animate-[wave_0.9s_ease-in-out_infinite]`}
            style={{ animationDelay: `${d}s`, height: 4 }}
          />
        ))}
      </span>
      <span className="text-ink-muted text-[12px] whitespace-nowrap">말하는 중</span>
    </div>
  );
}
