import { fmt } from '../../lib/format';

interface RecordExcerptProps {
  source: string | null;
  quote: string | null;
  transcript: string | null;
  atSec: number | null;
  onSeek?: (sec: number) => void;
}

/** 같은 원문을 검토 화면과 리포트에서 동일하게 표시한다. */
export function RecordExcerpt({ source, quote, transcript, atSec, onSeek }: RecordExcerptProps) {
  return (
    <div className="mt-2 text-[13px] leading-relaxed">
      {atSec !== null &&
        (onSeek ? (
          <button
            type="button"
            onClick={() => onSeek(atSec)}
            className="text-brand rounded px-2 py-1 font-mono underline"
            aria-label={`${fmt(atSec)}로 이동`}
          >
            {fmt(atSec)}
          </button>
        ) : transcript ? (
          <details className="group inline-block max-w-full">
            <summary
              className="border-border-base text-brand cursor-pointer rounded-full border px-2.5 py-1 font-mono"
              aria-label={`${fmt(atSec)} 면접 답변 보기`}
            >
              {fmt(atSec)} · 답변 보기
            </summary>
            <blockquote className="border-brand/40 text-ink-muted mt-2 border-l-2 pl-3">
              “{transcript}”
            </blockquote>
          </details>
        ) : (
          <span className="text-ink-dim font-mono">{fmt(atSec)}</span>
        ))}
      {quote && (
        <blockquote className="border-border-base text-ink-muted mt-2 border-l-2 pl-3">
          <span className="text-ink-dim">{source ?? '지원서'} · </span>“{quote}”
        </blockquote>
      )}
      {transcript && (onSeek || atSec === null) && (
        <blockquote className="border-brand/40 text-ink-muted mt-2 border-l-2 pl-3">
          <span className="text-ink-dim">면접 답변 · </span>“{transcript}”
        </blockquote>
      )}
    </div>
  );
}
