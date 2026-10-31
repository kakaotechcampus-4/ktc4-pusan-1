import { preserveMemoFocus } from '../../lib/memoFocus';
/**
 * AI 꼬리질문 — 면접관 전용 (#212).
 *
 * 면접관은 말하면서 듣고 답을 판단하는 중이라 읽을 여유가 거의 없다. 그래서 질문
 * 문장만 둔다 — 근거 발화·도착 시각·상태는 넣지 않는다. 고를 것이 적어야 눈이
 * 한 번에 끝난다.
 *
 * 누르면 고정된다. 고정한 것은 위로 올라가고, 그 뒤에 새 꼬리질문이 와도 자리가
 * 밀리지 않는다 — 묻기 직전에 질문이 어디로 갔는지 찾게 되는 것이 이 화면에서
 * 가장 나쁘다. 서버에는 고정을 적는 API 가 없어 새로고침하면 풀린다.
 *
 * 꼬리질문이 없을 때도 패널을 그린다. aria-live 영역은 내용이 바뀌기 전에 이미
 * DOM 에 있어야 읽힌다 — 상자째 나타나면 스크린리더가 놓친다.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { useInterviewStore } from '../../stores/interviewStore';
import { visibleSuggestions } from '../../lib/visibleSuggestions';

export function SuggestionPanel() {
  const root = useRef<HTMLElement>(null);
  const nextFocus = useRef<string | null>(null);
  const suggestions = useInterviewStore((s) => s.suggestions);
  const togglePin = useInterviewStore((s) => s.toggleSuggestionPin);

  const [showQuestions, setShowQuestions] = useState(false);
  const expanded = useInterviewStore((s) => s.questionsExpanded);
  const toggleExpanded = useInterviewStore((s) => s.toggleQuestionsExpanded);
  const hidden = useInterviewStore((s) => s.hiddenSuggestionIds);
  const dismiss = useInterviewStore((s) => s.dismissSuggestion);
  const undo = useInterviewStore((s) => s.undoDismissSuggestion);
  const lastHidden = useInterviewStore((s) => s.lastHiddenSuggestionId);
  const gesture = useRef<{ id: string; x: number; y: number } | null>(null);
  const ordered = visibleSuggestions(suggestions).filter(
    (suggestion) => !hidden.includes(suggestion.id),
  );

  useLayoutEffect(() => {
    if (!nextFocus.current) return;
    const target = root.current?.querySelector<HTMLElement>(nextFocus.current);
    target?.focus({ preventScroll: true });
    nextFocus.current = null;
  }, [hidden, suggestions]);
  const hide = (id: string) => {
    nextFocus.current = '[data-suggestion-undo]';
    dismiss(id);
  };
  const restore = () => {
    nextFocus.current = lastHidden
      ? `[data-suggestion-id="${CSS.escape(lastHidden)}"] button`
      : null;
    undo();
  };

  return (
    // 영상 위에서도 기본 상태부터 글자를 읽을 수 있게 한다.
    <section
      ref={root}
      onMouseDown={preserveMemoFocus}
      className="glass interview-readable flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-3xl"
    >
      <div className="flex shrink-0 items-center gap-2 px-4 pt-3 pb-1.5">
        <h2 className="text-ink text-[15px] font-semibold">꼬리질문</h2>
        {/* 누를 수 있다는 것을 글로 밝힌다. 아이콘만으로는 눈으로도 소리로도 모른다 */}
        <span className="text-ink-dim text-[12px]">누르면 고정</span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={toggleExpanded}
          aria-expanded={expanded}
          className="min-h-11 rounded-lg px-2 py-1 text-xs underline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {expanded ? '줄이기' : '확대'}
        </button>
        {ordered.length > 0 && (
          <span className="bg-brand-tint text-brand-strong rounded-full px-2 py-0.5 text-[12px] font-semibold tabular-nums">
            {ordered.length}
          </span>
        )}
      </div>

      <label className="flex shrink-0 items-center gap-2 px-4 py-2 text-xs">
        <input
          type="checkbox"
          checked={showQuestions}
          onChange={(event) => setShowQuestions(event.target.checked)}
        />
        질문 문장 보기
      </label>
      {lastHidden && (
        <div role="status" className="flex items-center justify-between gap-2 px-4 py-2 text-xs">
          <span>질문을 지웠습니다.</span>
          <button type="button" data-suggestion-undo onClick={restore} className="underline">
            취소
          </button>
        </div>
      )}
      {/* 꼬리질문은 소리로는 오지 않고 화면에만 있다. 그래서 읽어 주는 것이 맞다 */}
      <div
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-3 pb-3"
      >
        {ordered.length === 0 ? (
          <p className="text-ink-muted px-1.5 py-1 text-[14px]">
            대화가 이어지면 여기에 올라옵니다.
          </p>
        ) : (
          ordered.map((s) => (
            <div
              key={s.id}
              data-suggestion-id={s.id}
              className="flex shrink-0 gap-1"
              style={{ touchAction: 'pan-y' }}
              onPointerDown={(event) => {
                gesture.current = { id: s.id, x: event.clientX, y: event.clientY };
              }}
              onPointerCancel={() => {
                gesture.current = null;
              }}
              onPointerUp={(event) => {
                const start = gesture.current;
                gesture.current = null;
                if (
                  start?.id === s.id &&
                  Math.abs(event.clientX - start.x) >= 64 &&
                  Math.abs(event.clientX - start.x) > Math.abs(event.clientY - start.y) * 1.5
                ) {
                  event.preventDefault();
                  hide(s.id);
                }
              }}
            >
              <button
                type="button"
                onClick={() => togglePin(s.id)}
                aria-pressed={s.pinned}
                className={`flex min-w-0 flex-1 animate-[caption-in_.35s_ease-out] items-start gap-2.5 rounded-2xl border px-3 py-2.5 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 ${
                  s.pinned
                    ? 'border-brand/40 bg-brand-tint'
                    : 'border-border-base bg-surface-panel hover:bg-surface-container'
                }`}
              >
                <span
                  aria-hidden
                  className={`material-symbols-outlined mt-0.5 text-[18px] ${
                    s.pinned ? 'text-brand' : 'text-ink-dim'
                  }`}
                  style={s.pinned ? { fontVariationSettings: "'FILL' 1" } : undefined}
                >
                  push_pin
                </span>
                {/* 질문 글자는 고정 여부와 무관하게 가장 진한 색을 쓴다 — 읽어야 하는 것이다 */}
                <span
                  className={`text-ink flex-1 text-[15px] leading-relaxed ${
                    s.pinned ? 'font-semibold' : ''
                  }`}
                >
                  {s.reason || s.content}
                  {s.reason && showQuestions && (
                    <span className="text-ink-muted mt-1 block text-sm font-normal">
                      {s.content}
                    </span>
                  )}
                </span>
              </button>
              <button
                type="button"
                onClick={() => hide(s.id)}
                aria-label={`${s.content} 지우기`}
                className="text-ink-muted shrink-0 self-center rounded-lg px-2 py-3 text-xs hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                지우기
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
