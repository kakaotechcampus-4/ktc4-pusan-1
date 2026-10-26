/**
 * 실시간 전사 — 시안의 LIVE SCRIPT 패널.
 *
 * 면접관 도구 열의 아래 카드다 (#232). 마지막 줄은 지금 오가는 말이므로 왼쪽에 화자 색 띠를 붙여 눈이 먼저 가게 한다.
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
    <section className="border-border-base bg-surface-panel shadow-card shrink-0 overflow-hidden rounded-2xl border">
      {/* 헤더 전체가 접기 버튼이다. 말하면서 누르는 것이라 누를 곳이 넓어야 한다 */}
      <button
        type="button"
        onClick={toggleTranscript}
        aria-expanded={transcriptOpen}
        className={`flex w-full items-center gap-2 px-4 py-3 text-left ${transcriptOpen ? 'border-border-base border-b' : ''}`}
      >
        <span className="bg-danger h-2 w-2 animate-pulse rounded-full" />
        <span className="text-ink text-[15px] font-semibold">자동 기록</span>
        <span className="flex-1" />
        <span className="text-ink-muted text-[12px]">{transcriptOpen ? '접기' : '펼치기'}</span>
        {/* 버튼 안이라 실제 button 을 겹쳐 쓰지 못한다. 모양만 시안의 동그란 컨트롤을 따른다 */}
        <span className="text-ink-muted bg-surface-bright flex h-6 w-6 items-center justify-center rounded-full">
          <span className="material-symbols-outlined text-[16px]">
            {transcriptOpen ? 'expand_more' : 'expand_less'}
          </span>
        </span>
      </button>

      {transcriptOpen && (
        <div className="flex max-h-56 flex-col gap-1 overflow-y-auto px-2.5 py-3">
          {transcriptDegraded && (
            <p className="text-warning px-1.5 text-[14px] leading-relaxed">
              기록이 중단되었습니다. 통화는 계속됩니다.
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
                  latest ? `bg-surface-container ${st.border}` : 'border-transparent'
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
