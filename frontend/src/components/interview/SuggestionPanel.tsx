import { preserveMemoFocus } from '../../lib/memoFocus';
/**
 * AI 꼬리질문 — 면접관 전용 (#212).
 *
 * 면접관은 말하면서 듣고 답을 판단하는 중이라 읽을 여유가 거의 없다. 그래서 질문
 * 문장만 둔다 — 근거 발화·도착 시각·상태는 넣지 않는다. 고를 것이 적어야 눈이
 * 한 번에 끝난다.
 *
 * 질문은 큐로 흐른다. 고정하지 않은 질문은 최신 6개(또는 10개)만 두고, 새 질문이 오면
 * 가장 오래된 것이 빠진다. 누르면 고정되어 큐 밖 위쪽에 남고, 풀면 원래 순서 자리로
 * 돌아간다 — 그 자리가 이미 지났으면 사라진다. 지운 칸은 다음 질문이 채운다. 그래서 취소는
 * 지운 직후에만 둔다 — 새 질문이 그 칸을 채우면 되살릴 자리가 없다.
 * 지우기 · 고정은 서버에 적는 API 가 없어 이 탭에만 남는다(새로고침해도 유지).
 *
 * 꼬리질문이 없을 때도 패널을 그린다. aria-live 영역은 내용이 바뀌기 전에 이미
 * DOM 에 있어야 읽힌다 — 상자째 나타나면 스크린리더가 놓친다.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { queueOf, useInterviewStore } from '../../stores/interviewStore';
import {
  newestSuggestion,
  PIN_LIMIT,
  SUGGESTION_LIMITS,
  visibleSuggestions,
} from '../../lib/suggestionQueue';

export function SuggestionPanel() {
  const root = useRef<HTMLElement>(null);
  const nextFocus = useRef<string | null>(null);
  const suggestions = useInterviewStore((s) => s.suggestions);
  const togglePin = useInterviewStore((s) => s.toggleSuggestionPin);

  const [showReasons, setShowReasons] = useState(false);
  const expanded = useInterviewStore((s) => s.questionsExpanded);
  const toggleExpanded = useInterviewStore((s) => s.toggleQuestionsExpanded);
  const limit = useInterviewStore((s) => s.suggestionLimit);
  const setLimit = useInterviewStore((s) => s.setSuggestionLimit);
  const frozen = useInterviewStore((s) => s.frozenSuggestionIds);
  const togglePaused = useInterviewStore((s) => s.toggleSuggestionsPaused);
  const hidden = useInterviewStore((s) => s.hiddenSuggestionIds);
  const dismiss = useInterviewStore((s) => s.dismissSuggestion);
  const undo = useInterviewStore((s) => s.undoDismissSuggestion);
  const lastHidden = useInterviewStore((s) => s.lastHiddenSuggestionId);
  const ordered = useInterviewStore(useShallow((s) => visibleSuggestions(queueOf(s))));
  const newest = useInterviewStore((s) => newestSuggestion(queueOf(s)));
  const latestId = newest?.id;
  // 고정은 큐 밖에 쌓이므로 상한에 닿으면 더 못 고정한다 — 풀기는 언제나 된다.
  const pinFull = ordered.filter((s) => s.pinned).length >= PIN_LIMIT;

  // 지운 카드 · 취소 버튼이 사라져도 키보드 포커스가 body 로 빠지지 않게 옮긴다.
  useLayoutEffect(() => {
    if (!nextFocus.current) return;
    const target =
      root.current?.querySelector<HTMLElement>(nextFocus.current) ??
      root.current?.querySelector<HTMLButtonElement>('button');
    target?.focus({ preventScroll: true });
    nextFocus.current = null;
  }, [hidden, suggestions]);
  const hide = (id: string) => {
    const item = root.current?.querySelector(`[data-suggestion-id="${CSS.escape(id)}"]`);
    nextFocus.current = item?.contains(document.activeElement) ? '[data-suggestion-undo]' : null;
    dismiss(id);
  };
  const restore = () => {
    nextFocus.current =
      lastHidden && root.current?.querySelector('[data-suggestion-undo]') === document.activeElement
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
      {/* 머리와 줄 모양을 실시간 자막 패널에 맞춘다. 두 판이 한 화면에서 같은 말투로 읽힌다 */}
      <div className="flex w-full shrink-0 items-center gap-2 px-4 py-2.5">
        <span aria-hidden className="bg-brand h-2 w-2 rounded-full" />
        <h2 className="text-ink text-[14px] font-semibold">꼬리질문</h2>
        {/* 누를 수 있다는 것을 글로 밝힌다. 아이콘만으로는 눈으로도 소리로도 모른다 */}
        <span id="suggestion-pin-hint" className="text-ink-dim text-[12px]">
          누르면 고정
        </span>
        {/* 고정된 카드는 누르면 풀린다 — 같은 문구를 읽어 주면 반대로 알려 주는 셈이다 */}
        <span id="suggestion-unpin-hint" className="sr-only">
          누르면 고정 해제
        </span>
        <span id="suggestion-pin-full-hint" className="sr-only">
          고정은 {PIN_LIMIT}개까지입니다. 먼저 하나를 풀어 주세요
        </span>
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

      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 px-4 pb-1.5 text-xs">
        <label className="flex min-h-11 items-center gap-2 rounded-lg focus-within:outline-2 focus-within:outline-offset-2">
          <input
            type="checkbox"
            checked={showReasons}
            onChange={(event) => setShowReasons(event.target.checked)}
          />
          근거 보기
        </label>
        <span className="flex-1" />
        <div
          role="group"
          aria-label="표시 개수"
          className="flex gap-0.5 rounded-lg bg-white/10 p-0.5"
        >
          {SUGGESTION_LIMITS.map((n) => (
            <button
              key={n}
              type="button"
              aria-pressed={limit === n}
              onClick={() => setLimit(n)}
              className={`min-h-9 rounded-md px-2.5 font-semibold tabular-nums transition focus-visible:outline-2 focus-visible:-outline-offset-2 ${
                limit === n
                  ? 'bg-surface-panel text-ink shadow-card'
                  : 'text-ink-muted hover:text-ink'
              }`}
            >
              {n}개
            </button>
          ))}
        </div>
        {/* 자동으로 바뀌는 영역은 멈출 수 있어야 한다 (KWCAG 정지 기능) */}
        <button
          type="button"
          aria-pressed={frozen !== null}
          onClick={togglePaused}
          className="text-ink-muted hover:text-ink inline-flex min-h-9 items-center gap-1 rounded-lg px-2 font-semibold focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          <span aria-hidden className="material-symbols-outlined text-[16px]">
            {frozen ? 'play_arrow' : 'pause'}
          </span>
          {frozen ? '다시 흐르기' : '일시정지'}
        </button>
      </div>
      {lastHidden && (
        <div role="status" className="flex items-center justify-between gap-2 px-4 py-1 text-xs">
          <span>질문을 지웠습니다.</span>
          <button
            type="button"
            data-suggestion-undo
            onClick={restore}
            className="min-h-11 px-2 underline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            취소
          </button>
        </div>
      )}
      {/* 꼬리질문은 소리로는 오지 않고 화면에만 있다. 그래서 새로 온 질문 문장만 읽어 준다.
          목록 전체에 aria-live 를 걸면 지우기 버튼 이름까지 섞여 두 번 읽힌다 */}
      <p aria-live="polite" className="sr-only">
        {newest ? `새 꼬리질문: ${newest.content}` : ''}
      </p>
      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto overscroll-contain px-2.5 pb-3">
        {ordered.length === 0 ? (
          <p className="text-ink-dim px-1.5 text-[14px]">대화가 이어지면 여기에 올라옵니다.</p>
        ) : (
          ordered.map((s) => {
            // 막 들어온 질문은 자막의 지금 줄처럼 띠와 바탕으로 먼저 눈에 띄게 한다.
            // 띠는 자리를 늘 잡아 두고 색만 바꾼다 — 줄마다 들여쓰기가 흔들리지 않게.
            const latest = s.id === latestId;
            return (
              <div
                key={s.id}
                data-suggestion-id={s.id}
                className={`flex shrink-0 animate-[caption-in_.35s_ease-out] items-start gap-1 rounded-xl border-l-2 transition ${
                  s.pinned
                    ? 'border-brand bg-brand-tint'
                    : latest
                      ? 'border-accent bg-surface-container'
                      : 'hover:bg-surface-container border-transparent'
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    if (!s.pinned && pinFull) return;
                    togglePin(s.id);
                  }}
                  aria-pressed={s.pinned}
                  // disabled 로 두면 질문 글자에 포커스가 가지 않아 소리로 읽을 수 없다.
                  aria-disabled={!s.pinned && pinFull}
                  // 화면낭독기에서 「전환 버튼」만 들리지 않게 무엇을 켜는지 함께 알린다
                  aria-describedby={
                    s.pinned
                      ? 'suggestion-unpin-hint'
                      : pinFull
                        ? 'suggestion-pin-full-hint'
                        : 'suggestion-pin-hint'
                  }
                  className="flex min-w-0 flex-1 items-baseline gap-2 rounded-xl py-1.5 pr-1 pl-2.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2"
                >
                  <span
                    aria-hidden
                    className={`material-symbols-outlined shrink-0 self-start pt-1 text-[16px] ${
                      s.pinned ? 'text-brand' : 'text-ink-dim'
                    }`}
                    style={s.pinned ? { fontVariationSettings: "'FILL' 1" } : undefined}
                  >
                    push_pin
                  </span>
                  {/* 질문 글자는 고정 여부와 무관하게 가장 진한 색을 쓴다 — 읽어야 하는 것이다 */}
                  <span
                    className={`text-ink flex-1 leading-relaxed ${
                      s.pinned || latest ? 'text-[16px] font-semibold' : 'text-[15px]'
                    }`}
                  >
                    {s.content}
                    {s.reason && showReasons && (
                      <span className="text-ink-muted mt-1 block text-sm font-normal">
                        {s.reason}
                      </span>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => hide(s.id)}
                  // 보이는 글자를 이름 앞에 둔다 (KWCAG 레이블과 네임)
                  aria-label={`지우기: ${s.content}`}
                  className="text-ink-muted hover:text-ink shrink-0 self-center rounded-lg px-2 py-2.5 text-xs focus-visible:outline-2 focus-visible:-outline-offset-2"
                >
                  지우기
                </button>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
