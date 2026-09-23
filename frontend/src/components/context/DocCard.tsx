/**
 * 문서 한 건. 상태에 따라 다른 것을 보여준다.
 */

import { fmtSize } from '../../lib/docFile';
import type { ContextDoc } from '../../types/interview';

const STATUS_TEXT = (doc: ContextDoc) =>
  ({
    uploading: `올리는 중 ${Math.round((doc.progress ?? 0) * 100)}%`,
    parsing: '읽는 중',
    ready: `${fmtSize(doc.sizeBytes)} · ${doc.kind.toUpperCase()}`,
    failed: '읽지 못했습니다',
  })[doc.status];

export interface DocCardProps {
  doc: ContextDoc;
  /** 없으면 삭제 버튼을 감춘다 (업로드 중) */
  onDelete?: () => void;
}

export function DocCard({ doc, onDelete }: DocCardProps) {
  return (
    <div className="border-border-base bg-surface-container flex min-w-0 items-center gap-4 rounded-xl border px-5 py-4">
      <span
        aria-hidden
        className="bg-surface-bright text-ink-muted flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-mono text-[11px] font-semibold"
      >
        {doc.kind.toUpperCase()}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-ink truncate text-[15px]">{doc.name}</span>
        <span
          className={`font-mono text-[12px] ${
            doc.status === 'failed' ? 'text-[#FF8A8A]' : 'text-ink-dim'
          }`}
        >
          {STATUS_TEXT(doc)}
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
  );
}
