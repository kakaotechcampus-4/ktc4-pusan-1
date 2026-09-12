import { fmt } from '../../lib/format';
import { useInterviewStore } from '../../stores/interviewStore';
import { SPEAKER_STYLE } from './speakerStyle';

export function TranscriptPanel() {
  const utterances = useInterviewStore((s) => s.utterances);
  const transcriptOpen = useInterviewStore((s) => s.transcriptOpen);
  const transcriptDegraded = useInterviewStore((s) => s.transcriptDegraded);
  const toggleTranscript = useInterviewStore((s) => s.toggleTranscript);

  return (
    <div className="pointer-events-auto w-[520px] max-w-[42vw] overflow-hidden rounded-xl bg-black/55 backdrop-blur-md">
      <button
        onClick={toggleTranscript}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 text-left"
      >
        <span className="h-2 w-2 rounded-full bg-[#2B44D6]" />
        <span className="text-[15px] font-semibold text-white">자동 기록</span>
        <span className="flex-1" />
        <span className="text-sm text-white/50">{transcriptOpen ? '접기 ⌄' : '펼치기 ⌃'}</span>
      </button>

      {transcriptOpen && (
        <div className="flex flex-col gap-3 px-5 pb-5">
          {transcriptDegraded && (
            <p className="text-[15px] leading-relaxed text-[#FFC46B]">
              기록이 중단되었습니다. 통화와 녹화는 계속됩니다.
            </p>
          )}

          {utterances.length === 0 && !transcriptDegraded && (
            <p className="text-[15px] text-white/45">대화가 시작되면 여기에 기록됩니다.</p>
          )}

          {utterances.map((u) => (
            <div key={u.id} className="flex gap-3">
              <span className="w-[52px] shrink-0 pt-0.5 font-mono text-[13px] text-white/45">
                {fmt(u.atSec)}
              </span>
              <span
                className={`w-[52px] shrink-0 pt-0.5 text-[13px] font-semibold ${
                  SPEAKER_STYLE[u.speaker].text
                }`}
              >
                {SPEAKER_STYLE[u.speaker].label}
              </span>
              <p className="flex-1 text-[17px] leading-relaxed text-white">{u.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
