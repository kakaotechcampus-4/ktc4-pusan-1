/**
 * 텍스트를 붙여넣어 문서로 등록한다.
 *
 * JD 는 대개 채용 공고에서 복사할 수 있다. 파일로 올리면 서버가 형식을 판별하고 글자를
 * 뽑아내야 하지만, 텍스트는 그대로 저장하면 끝이다 — 가장 싸고 가장 빨리 끝나는 경로다.
 */

import { useState } from 'react';

/** 제목을 비워도 되게 두되, 목록에서 구분은 되어야 한다. */
const FALLBACK_TITLE = '붙여넣은 텍스트';

/** 실수로 문서 전체를 붙여넣는 경우를 막는다. 서버 저장 한도와 맞춘다. */
const MAX_CHARS = 50_000;

export interface TextPasteProps {
  onSubmit: (title: string, body: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function TextPaste({ onSubmit, disabled, placeholder }: TextPasteProps) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');

  const tooLong = body.length > MAX_CHARS;
  const canSubmit = Boolean(body.trim()) && !tooLong && !disabled;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(title.trim() || FALLBACK_TITLE, body.trim());
    setTitle('');
    setBody('');
  };

  return (
    <div className="flex flex-col gap-2.5">
      <input
        type="text"
        value={title}
        disabled={disabled}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="제목 (예: 백엔드 엔지니어 JD)"
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand w-full rounded-xl border px-4 py-2.5 text-[14px] outline-none"
      />

      <textarea
        value={body}
        disabled={disabled}
        onChange={(e) => setBody(e.target.value)}
        rows={6}
        placeholder={placeholder ?? '채용 공고나 문서 내용을 붙여넣으세요.'}
        className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim focus:border-brand w-full resize-y rounded-xl border p-4 text-[14px] leading-relaxed outline-none"
      />

      <div className="flex items-center gap-3">
        <span className={`font-mono text-[12px] ${tooLong ? 'text-[#FFC46B]' : 'text-ink-dim'}`}>
          {body.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}자
        </span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="bg-brand disabled:bg-surface-bright disabled:text-ink-dim rounded-lg px-4 py-2 text-[14px] font-medium text-white transition hover:bg-blue-700"
        >
          텍스트 추가
        </button>
      </div>
    </div>
  );
}
