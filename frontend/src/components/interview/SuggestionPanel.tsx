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

import { useInterviewStore } from '../../stores/interviewStore';

export function SuggestionPanel() {
  const suggestions = useInterviewStore((s) => s.suggestions);
  const togglePin = useInterviewStore((s) => s.toggleSuggestionPin);

  // 고정한 것을 위로 올린다. sort 가 안정적이라 그 안에서는 도착 순서가 유지된다.
  const ordered = [...suggestions].sort((a, b) => Number(b.pinned) - Number(a.pinned));

  return (
    <section className="pointer-events-auto w-[340px] max-w-[34vw] overflow-hidden rounded-2xl border border-white/10 bg-black/55 shadow-[0_16px_36px_rgba(0,0,0,.35)] backdrop-blur-xl">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
        <span aria-hidden className="material-symbols-outlined text-brand-soft text-[18px]">
          auto_awesome
        </span>
        <h2 className="text-ink text-[13px] font-semibold">꼬리질문</h2>
        {/* 누를 수 있다는 것을 글로 밝힌다. 아이콘만으로는 눈으로도 소리로도 모른다 */}
        <span className="text-ink-muted text-[12px]">· 누르면 고정</span>
        <span className="flex-1" />
        {suggestions.length > 0 && (
          <span className="text-ink-muted font-mono text-[12px]">{suggestions.length}</span>
        )}
      </div>

      {/* 꼬리질문은 소리로는 오지 않고 화면에만 있다. 그래서 읽어 주는 것이 맞다 */}
      <div aria-live="polite" className="flex max-h-[42vh] flex-col gap-1.5 overflow-y-auto p-2.5">
        {ordered.length === 0 ? (
          <p className="text-ink-muted px-1.5 py-1 text-[13px]">
            대화가 이어지면 여기에 올라옵니다.
          </p>
        ) : (
          ordered.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => togglePin(s.id)}
              aria-pressed={s.pinned}
              className={`focus-visible:ring-brand-soft flex items-start gap-2 rounded-xl border-l-2 px-2.5 py-2 text-left transition focus-visible:ring-2 focus-visible:outline-none ${
                s.pinned
                  ? 'border-brand-soft bg-brand/30'
                  : 'border-transparent bg-white/5 hover:bg-white/10'
              }`}
            >
              <span
                aria-hidden
                className={`material-symbols-outlined mt-0.5 text-[16px] ${
                  s.pinned ? 'text-brand-soft' : 'text-ink-muted'
                }`}
              >
                push_pin
              </span>
              {/* 질문 글자는 고정 여부와 무관하게 가장 밝은 색을 쓴다 — 읽어야 하는 것이다 */}
              <span
                className={`text-ink flex-1 text-[14px] leading-relaxed ${
                  s.pinned ? 'font-semibold' : ''
                }`}
              >
                {s.content}
              </span>
            </button>
          ))
        )}
      </div>
    </section>
  );
}
