import { preserveMemoFocus } from '../../lib/memoFocus';
/**
 * 실시간 전사 — 시안의 LIVE SCRIPT 패널.
 *
 * 영상 위 왼쪽 아래에 뜬 유리판이다 (#236). 지난 줄은 흐리게 두다가 마우스를 올리면
 * 또렷해지고, 지금 오가는 마지막 줄은 늘 읽히게 둔다. 새 줄은 아래에서 떠오르고
 * 목록은 늘 마지막 줄을 따라 내려간다. 마지막 줄은 지금 오가는 말이므로 왼쪽에 화자 색 띠를 붙여 눈이 먼저 가게 한다.
 */

import { useEffect, useRef, useState } from 'react';
import { fmt } from '../../lib/format';
import { useInterviewStore } from '../../stores/interviewStore';
import { SPEAKER_STYLE } from './speakerStyle';

export function TranscriptPanel() {
  const utterances = useInterviewStore((s) => s.utterances);
  const transcriptOpen = useInterviewStore((s) => s.transcriptOpen);
  const transcriptDegraded = useInterviewStore((s) => s.transcriptDegraded);
  const toggleTranscript = useInterviewStore((s) => s.toggleTranscript);

  // 새 줄이 오거나 지금 줄이 길어지면 맨 아래를 보인다. 자막을 읽다가 스크롤을 찾게 되면 늦는다.
  // 다만 지난 줄을 읽으려고 위로 올리면 따라 내려가기를 멈춘다 (KWCAG 정지 기능).
  const listRef = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const last = utterances.at(-1);
  const toBottom = () => {
    const list = listRef.current;
    if (!list) return;
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    list.scrollTo({ top: list.scrollHeight, behavior: still ? 'auto' : 'smooth' });
  };
  useEffect(() => {
    if (following) toBottom();
  }, [last?.id, last?.text, transcriptOpen, following]);

  return (
    <section className="glass interview-readable flex h-full min-h-0 flex-col overflow-hidden rounded-3xl">
      {/* 헤더 전체가 접기 버튼이다. 말하면서 누르는 것이라 누를 곳이 넓어야 한다 */}
      <button
        type="button"
        onClick={toggleTranscript}
        onMouseDown={preserveMemoFocus}
        aria-expanded={transcriptOpen}
        // 패널이 overflow-hidden 이라 바깥 테두리는 잘린다. 초점 테두리를 안쪽에 그린다 (KWCAG 초점 표시)
        className="glass-dim flex w-full shrink-0 items-center gap-2 rounded-t-3xl px-4 py-2.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-4"
      >
        <span className="h-2 w-2 animate-pulse rounded-full bg-[#ff5a63]" />
        <span className="text-ink text-[14px] font-semibold">실시간 자막</span>
        <span className="flex-1" />
        <span className="text-ink-muted text-[12px]">{transcriptOpen ? '접기' : '펼치기'}</span>
        {/* 버튼 안이라 실제 button 을 겹쳐 쓰지 못한다. 모양만 시안의 동그란 컨트롤을 따른다 */}
        <span className="text-ink-muted bg-surface-bright flex h-6 w-6 items-center justify-center rounded-full">
          <span aria-hidden className="material-symbols-outlined text-[16px]">
            {transcriptOpen ? 'expand_more' : 'expand_less'}
          </span>
        </span>
      </button>

      {transcriptOpen && !following && (
        <button
          type="button"
          onClick={() => setFollowing(true)}
          onMouseDown={preserveMemoFocus}
          className="text-ink-muted hover:text-ink mx-auto mt-1 flex shrink-0 items-center gap-1 rounded-full px-3 py-1 text-[12px] font-semibold focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          <span aria-hidden className="material-symbols-outlined text-[16px]">
            arrow_downward
          </span>
          최신 자막으로
        </button>
      )}

      {transcriptOpen && (
        <div
          ref={listRef}
          // 멈춤은 사람이 위로 올릴 때만 건다. 자동으로 내려가는 중의 scroll 이벤트로는 멈추지 않는다.
          onWheel={(event) => event.deltaY < 0 && setFollowing(false)}
          onTouchMove={() => setFollowing(false)}
          onKeyDown={(event) =>
            ['ArrowUp', 'PageUp', 'Home'].includes(event.key) && setFollowing(false)
          }
          // 다시 맨 아래까지 내리면 따라가기를 잇는다.
          onScroll={(event) => {
            const list = event.currentTarget;
            if (list.scrollHeight - list.scrollTop - list.clientHeight < 24) setFollowing(true);
          }}
          // 키보드로도 지난 자막을 올려 읽을 수 있게 초점을 받는다
          tabIndex={0}
          role="region"
          aria-label="실시간 자막 기록"
          className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto overscroll-contain px-2.5 pb-3"
        >
          {transcriptDegraded && (
            <p className="text-warning px-1.5 text-[14px] leading-relaxed">
              기록이 중단되었습니다. 통화는 계속됩니다.
            </p>
          )}

          {utterances.length === 0 && !transcriptDegraded && (
            <p className="glass-dim text-ink-dim px-1.5 text-[14px]">
              대화가 시작되면 여기에 자막이 올라옵니다.
            </p>
          )}

          {utterances.map((u, i) => {
            const st = SPEAKER_STYLE[u.speaker];
            // 마지막 줄이 곧 현재 발화다. 띠는 자리를 늘 잡아 두고 색만 바꾼다 —
            // 줄이 바뀔 때마다 들여쓰기가 흔들리면 읽기 어렵다.
            const latest = i === utterances.length - 1;

            return (
              // key 가 발화 id 라 새 줄만 새로 그려지고, 그 줄만 떠오른다. 같은 줄이
              // 길어지는 것(중간 결과 → 확정)은 다시 떠오르지 않는다.
              <div
                key={u.id}
                className={`${latest ? '' : 'glass-dim'} flex animate-[caption-in_.35s_ease-out] items-baseline gap-2 rounded-xl border-l-2 py-1.5 pr-2 pl-2.5 ${
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
                  className={`flex-1 leading-relaxed ${
                    latest ? 'text-ink text-[16px] font-semibold' : 'text-ink-muted text-[14px]'
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
