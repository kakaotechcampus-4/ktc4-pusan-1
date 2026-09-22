/**
 * 실시간 전사 — 시안의 LIVE SCRIPT 패널.
 *
 * 영상 위에 뜨는 글이라 유리판(반투명 + blur)으로 깔고 테두리로 경계를 준다.
 * 마지막 줄은 지금 오가는 말이므로 왼쪽에 화자 색 띠를 붙여 눈이 먼저 가게 한다.
 */

import { fmt } from '../../lib/format';
import { useInterviewStore } from '../../stores/interviewStore';
import { SPEAKER_STYLE } from './speakerStyle';

export function TranscriptPanel() {
  const utterances = useInterviewStore((s) => s.utterances);
  const transcriptOpen = useInterviewStore((s) => s.transcriptOpen);
  const transcriptDegraded = useInterviewStore((s) => s.transcriptDegraded);
  const toggleTranscript = useInterviewStore((s) => s.toggleTranscript);

  return (
    <section className="pointer-events-auto relative w-[520px] max-w-[42vw] overflow-hidden rounded-2xl border border-white/10 bg-black/50 shadow-[0_16px_36px_rgba(0,0,0,.35)] backdrop-blur-xl">
      {/* 시안의 배경 워터마크. 패널이 무엇인지 글자 없이 알린다 */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center justify-center text-6xl font-black tracking-tighter text-white opacity-5 select-none"
      >
        LIVE SCRIPT
      </span>

      {/* 헤더 전체가 접기 버튼이다. 영상 위라 누를 곳이 넓어야 한다 */}
      <button
        onClick={toggleTranscript}
        className="relative flex w-full items-center gap-2 border-b border-white/10 px-4 py-2.5 text-left"
      >
        <span className="bg-brand-soft h-1.5 w-1.5 rounded-full" />
        <span className="text-ink text-[13px] font-semibold">자동 기록</span>
        <span className="flex-1" />
        <span className="text-ink-muted text-[12px]">{transcriptOpen ? '접기' : '펼치기'}</span>
        {/* 버튼 안이라 실제 button 을 겹쳐 쓰지 못한다. 모양만 시안의 동그란 컨트롤을 따른다 */}
        <span className="text-ink-muted flex h-5 w-5 items-center justify-center rounded-full bg-white/10">
          <span className="material-symbols-outlined text-[16px]">
            {transcriptOpen ? 'expand_more' : 'expand_less'}
          </span>
        </span>
      </button>

      {transcriptOpen && (
        <div className="relative flex max-h-44 flex-col gap-1 overflow-y-auto px-2.5 py-3">
          {transcriptDegraded && (
            <p className="px-1.5 text-[14px] leading-relaxed text-amber-300">
              기록이 중단되었습니다. 통화와 녹화는 계속됩니다.
            </p>
          )}

          {utterances.length === 0 && !transcriptDegraded && (
            <p className="text-ink-dim px-1.5 text-[14px]">대화가 시작되면 여기에 기록됩니다.</p>
          )}

          {utterances.map((u, i) => {
            const st = SPEAKER_STYLE[u.speaker];
            // 마지막 줄이 곧 현재 발화다. 띠는 자리를 늘 잡아 두고 색만 바꾼다 —
            // 줄이 바뀔 때마다 들여쓰기가 흔들리면 읽기 어렵다.
            const latest = i === utterances.length - 1;

            return (
              <div
                key={u.id}
                className={`flex items-baseline gap-2 rounded-lg border-l-2 py-1 pr-1.5 pl-2 ${
                  latest ? `bg-white/5 ${st.border}` : 'border-transparent'
                }`}
              >
                <span
                  className={`w-10 shrink-0 font-mono text-[12px] ${
                    latest ? st.text : 'text-ink-dim'
                  }`}
                >
                  {fmt(u.atSec)}
                </span>
                <span className={`w-11 shrink-0 text-[12px] font-semibold ${st.text}`}>
                  {st.label}
                </span>
                <p
                  className={`flex-1 text-[14px] leading-relaxed ${
                    latest ? 'text-ink font-semibold' : 'text-ink-muted'
                  }`}
                >
                  {u.text}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
