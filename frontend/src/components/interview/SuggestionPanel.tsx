import { useInterviewStore } from '../../stores/interviewStore';

export function SuggestionPanel() {
  const suggestions = useInterviewStore((s) => s.suggestions);
  const suggestionsOpen = useInterviewStore((s) => s.suggestionsOpen);
  const toggleSuggestions = useInterviewStore((s) => s.toggleSuggestions);
  const markAsked = useInterviewStore((s) => s.markAsked);

  // 서버에 알리는 엔드포인트가 BE 명세(2026-09-08)에 없다.
  // 지금은 화면에서만 표시하고, 엔드포인트가 생기면 낙관적 갱신 + 실패 시 롤백을 붙인다.
  // unmarkAsked 는 그때 쓰인다.
  const ask = (id: string) => markAsked(id);

  return (
    <div className="pointer-events-auto w-[400px] max-w-[32vw] overflow-hidden rounded-xl bg-black/55 backdrop-blur-md">
      <button
        onClick={toggleSuggestions}
        className="flex w-full items-center gap-2.5 px-5 py-3.5 text-left"
      >
        <span className="h-2 w-2 rounded-full bg-[#2B44D6]" />
        <span className="text-[15px] font-semibold text-white">이어서 물어볼 질문</span>
        <span className="flex-1" />
        <span className="text-sm text-white/50">{suggestionsOpen ? '접기 ⌄' : '펼치기 ⌃'}</span>
      </button>

      {/* 목록만 스크롤한다 — 헤더(접기)는 항상 눌릴 수 있어야 한다.
          질문은 3개까지만 쌓이므로 보통은 스크롤이 생기지 않는다.
          짧은 화면이나 질문이 길어 여러 줄로 감길 때를 위한 안전망이다. */}
      {suggestionsOpen && (
        <div className="flex max-h-[calc(100vh-11rem)] flex-col gap-2.5 overflow-y-auto px-5 pb-5">
          {suggestions.length === 0 && (
            <p className="text-[15px] text-white/45">지원자 답변이 끝나면 질문이 올라옵니다.</p>
          )}

          {suggestions.map((q) => (
            <div
              key={q.id}
              className={`rounded-lg border-l-[3px] bg-white/[0.07] p-3.5 ${
                q.asked ? 'border-[#1E9E6A]' : 'border-[#2B44D6]'
              }`}
            >
              <p className="text-[17px] leading-snug text-white">{q.text}</p>
              <p className="mt-1.5 text-[13px] text-white/50">{q.reason}</p>
              <button
                onClick={() => ask(q.id)}
                disabled={q.asked}
                className={`mt-3 rounded-md px-3.5 py-2 text-sm font-medium ${
                  q.asked
                    ? 'bg-[#1E9E6A]/20 text-[#5FD6A5]'
                    : 'bg-[#2B44D6] text-white hover:bg-[#243AB8]'
                }`}
              >
                {q.asked ? '물어봤음' : '물어보기'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
