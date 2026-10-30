/**
 * 면접 중 메모 — 면접관 전용 (#219).
 *
 * 리포트 맨 위 칸이 이 메모다(#238). 면접 중에 적어 둔 것이 저장되지 않으면 리포트의
 * 그 자리가 빈 채로 나간다. 그래서 「저장」 버튼 없이 입력이 멈추면 저장한다 —
 * 저장 규칙은 면접 기록 화면의 메모와 같은 훅을 쓴다(`useMemoAutosave`).
 *
 * 커서가 이 칸을 떠나지 않는 것이 규칙이다. 꼬리질문을 눌러도 포커스가 넘어오지 않게
 * 누르는 쪽에서 막는다(`SuggestionPanel`). 여기서 blur 를 잡아 다시 focus 하지는
 * 않는다 — 그러면 한글 조합이 글자 중간에 끊기고 캐럿이 글 끝으로 튄다.
 *
 * 흐리게(`glass-dim`) 두지 않는다. 면접관이 지금 보면서 쓰는 칸이라 마우스를 올려야
 * 또렷해지면 쓰는 동안 자기 글이 안 보인다.
 *
 * 면접 중에는 저장된 메모를 다시 읽을 API 가 없다 — 검토 조회는 요약이 준비되기 전까지
 * 202 이고 메모를 담지 않는다. 그래서 입력을 이 탭에도 남겨 두고, 새로고침으로 돌아오면
 * 복구한다. 다른 기기·다른 탭으로 다시 들어오면 빈 칸에서 시작한다.
 */

import { useEffect, useRef, useState } from 'react';
import { MEMO_MAX, useMemoAutosave } from '../../hooks/useMemoAutosave';

/** 글자 수를 적기 시작하는 지점. 상한이 멀면 숫자가 자리만 차지한다 */
const COUNT_FROM = MEMO_MAX - 500;

const draftKey = (sessionId: string) => `irya.memo.${sessionId}`;

/** 탭에 남겨 둔 입력. 사생활 보호 모드처럼 저장소를 막아 둔 브라우저에서는 던진다 */
const readDraft = (sessionId: string) => {
  try {
    return sessionStorage.getItem(draftKey(sessionId)) ?? '';
  } catch {
    return '';
  }
};

const writeDraft = (sessionId: string, value: string) => {
  try {
    sessionStorage.setItem(draftKey(sessionId), value);
  } catch {
    // 서버 저장이 본체다. 탭에 못 남겨도 메모가 사라지는 것은 아니다.
  }
};

export interface MemoPanelProps {
  /** 초안을 남겨 둘 자리를 가른다. 입장하자마자 알 수 있는 값이라 키로 쓴다 */
  sessionId: string;
  /** 저장할 면접. 방에 붙어 상태를 조회한 뒤에 온다 */
  interviewId: string | null;
}

export function MemoPanel({ sessionId, interviewId }: MemoPanelProps) {
  const [restored] = useState(() => readDraft(sessionId));
  const { memo, setMemo, state } = useMemoAutosave({ interviewId, initial: restored });
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // 복구한 초안은 한 번 보낸다 — 새로고침 직전에 적은 몇 글자는 아직 서버에 없을 수 있다.
    if (restored) setMemo(restored);
  }, [restored, setMemo]);

  useEffect(() => {
    // 커서가 아무 데도 아닌 곳(body)으로 떨어졌을 때만 되돌린다. 누를 것이 없는 자리는
    // 눌리는 쪽에서 막지만(`InterviewRoomView` · `SuggestionPanel`), 패널 안의 글자처럼
    // 막지 않은 자리가 남는다.
    //
    // mouseup 이 아니라 click 에서 본다 — 자막을 긁는 동안에 끼어들면 드래그가 끊긴다.
    // 아래 두 경우는 건드리지 않는다. 손대면 더 나빠지는 쪽이다.
    //   - 다른 요소가 포커스를 가져갔다(버튼 · Tab) → 키보드 사용자를 메모에 가두게 된다
    //   - 긁어 둔 글이 있다 → 돌려놓으면 그 글을 복사할 수 없다
    const back = () => {
      const el = box.current;
      if (!el || document.activeElement !== document.body) return;
      if (String(window.getSelection() ?? '') !== '') return;
      const [start, end] = [el.selectionStart, el.selectionEnd];
      el.focus();
      // 포커스만 돌려주면 캐럿이 글 끝으로 간다. 쓰던 자리를 그대로 돌려놓는다.
      el.setSelectionRange(start, end);
    };
    document.addEventListener('click', back);
    return () => document.removeEventListener('click', back);
  }, []);

  return (
    <section className="glass flex min-h-[8rem] flex-1 flex-col overflow-hidden rounded-3xl">
      <div className="flex shrink-0 items-center gap-2 px-4 pt-3 pb-1.5">
        <span aria-hidden className="material-symbols-outlined text-brand text-[20px]">
          edit_note
        </span>
        <h2 className="text-ink text-[15px] font-semibold">
          <label htmlFor="interview-memo">메모</label>
        </h2>
        <span className="flex-1" />
        {memo.length > COUNT_FROM && (
          <span className="text-ink-dim font-mono text-[12px] tabular-nums">
            {memo.length}/{MEMO_MAX}
          </span>
        )}
        <span
          aria-live="polite"
          className={`text-[12px] ${state === 'failed' ? 'text-danger' : 'text-ink-dim'}`}
        >
          {state === 'saving' && '저장 중…'}
          {state === 'saved' && '저장됨'}
          {state === 'failed' && '저장하지 못했습니다. 계속 입력하면 다시 시도합니다.'}
        </span>
      </div>

      {/* 입장하면 여기에 커서가 가 있다. 면접관이 먼저 할 일은 적는 것이다 */}
      <textarea
        id="interview-memo"
        ref={box}
        autoFocus
        maxLength={MEMO_MAX}
        value={memo}
        onChange={(e) => {
          setMemo(e.target.value);
          writeDraft(sessionId, e.target.value);
        }}
        placeholder="들은 것과 다음에 물어볼 것을 적어 두세요. 입력하면 자동으로 저장됩니다."
        // 포커스 테두리는 지우지 않는다. 지금 어디에 쓰고 있는지가 이 화면에서는 정보다
        className="text-ink placeholder:text-ink-dim min-h-0 flex-1 resize-none [scrollbar-width:none] bg-transparent px-4 pb-3 text-[15px] leading-relaxed [&::-webkit-scrollbar]:hidden"
      />
    </section>
  );
}
