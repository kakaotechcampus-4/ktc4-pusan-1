/**
 * 문서 한 건. 상태에 따라 다른 것을 보여준다.
 */

import { fmtSize } from '../../lib/docFile';
import type { ContextDoc } from '../../types/interview';

const STATUS_TEXT = (doc: ContextDoc) =>
  ({
    uploading: `올리는 중 ${Math.round((doc.progress ?? 0) * 100)}%`,
    parsing: '읽는 중',
    ready:
      doc.kind === 'text'
        ? `붙여넣은 텍스트 · ${fmtSize(doc.sizeBytes)}`
        : `${fmtSize(doc.sizeBytes)} · ${doc.kind.toUpperCase()}`,
    failed: '올리지 못했습니다',
  })[doc.status];

export interface DocCardProps {
  doc: ContextDoc;
  /** 없으면 삭제 버튼을 감춘다 (업로드 중) */
  onDelete?: () => void;
  /**
   * 실패한 업로드를 다시 시도한다.
   *
   * 없으면 버튼을 감춘다. 이게 없으면 사용자가 파일을 처음부터 다시 골라야 한다 —
   * 방금 고른 파일을 화면이 들고 있는데도.
   */
  onRetry?: () => void;
  /** 올려도 되지만 알아둘 점 — 예: 글자가 없는 스캔본 */
  warning?: string;
  /** 쪽수·예상 시간 같은 참고 정보 */
  hint?: string;
}

export function DocCard({ doc, onDelete, onRetry, warning, hint }: DocCardProps) {
  const failed = doc.status === 'failed';

  return (
    <div className="border-border-base bg-surface-container flex min-w-0 flex-col gap-2 rounded-xl border px-5 py-4">
      <div className="flex min-w-0 items-center gap-4">
        <span
          aria-hidden
          className="bg-surface-bright text-ink-muted flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-mono text-[11px] font-semibold"
        >
          {doc.kind === 'text' ? 'TXT' : doc.kind.toUpperCase()}
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-ink truncate text-[15px]">{doc.name}</span>
          <span className={`font-mono text-[12px] ${failed ? 'text-[#FF8A8A]' : 'text-ink-dim'}`}>
            {STATUS_TEXT(doc)}
            {hint && doc.status !== 'uploading' && ` · ${hint}`}
          </span>

          {doc.status === 'uploading' && (
            <span className="mt-1 h-1 w-full overflow-hidden rounded-full bg-white/10">
              <span
                className="bg-brand block h-full rounded-full transition-[width] duration-200"
                style={{ width: `${(doc.progress ?? 0) * 100}%` }}
              />
            </span>
          )}
        </div>

        {failed && onRetry && (
          <button
            type="button"
            onClick={onRetry}
            aria-label={`${doc.name} 다시 시도`}
            className="text-ink-muted hover:bg-surface-bright hover:text-ink shrink-0 rounded-md px-2 py-1 text-[13px] transition"
          >
            다시 시도
          </button>
        )}

        {onDelete && (
          <button
            type="button"
            onClick={onDelete}
            aria-label={`${doc.name} 삭제`}
            className="text-ink-dim hover:bg-surface-bright hover:text-ink shrink-0 rounded-md px-2 py-1 text-[13px] transition"
          >
            삭제
          </button>
        )}
      </div>

      {warning && <p className="text-[13px] leading-relaxed text-[#FFC46B]">{warning}</p>}
    </div>
  );
}
