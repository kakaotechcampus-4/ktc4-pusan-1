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
    // 서버가 다시 읽어 주지 않는다. 사람이 지우고 다시 올려야 한다 (#149).
    failed: '본문을 읽지 못했습니다. 지우고 다시 올려주세요',
  })[doc.status];

export interface DocCardProps {
  doc: ContextDoc;
  /** 없으면 삭제 버튼을 감춘다 (업로드 중) */
  onDelete?: () => void;
}

export function DocCard({ doc, onDelete }: DocCardProps) {
  return (
    <div className="border-border-base bg-surface-panel flex min-w-0 items-center gap-4 rounded-xl border px-4 py-3.5">
      <span
        aria-hidden
        className="bg-danger-tint text-danger flex h-10 w-10 shrink-0 items-center justify-center rounded-lg font-mono text-[11px] font-bold"
      >
        {doc.kind.toUpperCase()}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-ink truncate text-[15px] font-medium">{doc.name}</span>
        <span
          className={`inline-flex items-center gap-1.5 text-[12px] ${
            doc.status === 'failed'
              ? 'text-danger'
              : doc.status === 'ready'
                ? 'text-ink-dim'
                : 'text-brand'
          }`}
        >
          {doc.status === 'parsing' && (
            <span
              aria-hidden
              className="border-brand-tint border-t-brand h-3 w-3 animate-spin rounded-full border-2"
            />
          )}
          {STATUS_TEXT(doc)}
        </span>

        {doc.status === 'uploading' && (
          <span className="bg-surface-bright mt-1 h-1 w-full overflow-hidden rounded-full">
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
          className="text-ink-dim hover:bg-danger-tint hover:text-danger shrink-0 rounded-lg p-2 transition"
        >
          <span aria-hidden className="material-symbols-outlined text-[20px]">
            delete
          </span>
        </button>
      )}
    </div>
  );
}
