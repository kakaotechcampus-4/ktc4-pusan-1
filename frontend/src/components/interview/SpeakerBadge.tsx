import { useInterviewStore } from '../../stores/interviewStore';
import { SPEAKER_STYLE } from './speakerStyle';

export function SpeakerBadge() {
  const speakingNow = useInterviewStore((s) => s.speakingNow);
  if (!speakingNow) return null;
  const st = SPEAKER_STYLE[speakingNow];

  return (
    <div className="flex items-center gap-2.5 rounded-lg bg-black/55 px-3.5 py-2 backdrop-blur-md">
      <span className="flex h-3.5 items-end gap-[3px]">
        {[0, 0.12, 0.24].map((d) => (
          <span
            key={d}
            className={`w-[3px] ${st.bar} animate-[wave_0.7s_ease-in-out_infinite]`}
            style={{ animationDelay: `${d}s`, height: 4 }}
          />
        ))}
      </span>
      <span className={`text-sm font-semibold whitespace-nowrap ${st.text}`}>{st.label}</span>
      <span className="text-sm whitespace-nowrap text-white/60">말하는 중</span>
    </div>
  );
}
