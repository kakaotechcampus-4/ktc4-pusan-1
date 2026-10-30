/**
 * 검토 항목과 역량 커버리지 (#137 1-2 · 1-4).
 *
 * AI 가 근거와 함께 짚은 것을 면접관이 채택하거나 제외한다. 판정이 아니므로 AI 의
 * 말투로 결론을 적지 않고, 근거(지원서 문장 · 면접 발화)를 그대로 보여 준다.
 */

import { coverageLabel, progressNote } from '../../lib/findingsState';
import { FINDING_LABEL } from '../../lib/reviewLabels';
import { RecordExcerpt } from './RecordExcerpt';
import type { Coverage, Finding, FindingsStatus } from '../../types/interview';

const COVERAGE_STYLE: Record<Coverage['state'], string> = {
  CONFIRMED: 'border-accent/30 bg-accent-tint text-accent-strong',
  PARTIAL: 'border-warning/30 bg-warning-tint text-warning',
  MISSING: 'border-border-base bg-surface-bright text-ink-dim',
};

export interface FindingsProps {
  coverage: Coverage[];
  findings: Finding[];
  findingsStatus: FindingsStatus;
  onMark: (findingId: string, state: Finding['state']) => void;
  onSeek: (sec: number) => void;
  locked?: boolean;
  pendingIds?: ReadonlySet<string>;
}

export function Findings({
  coverage,
  findings,
  findingsStatus,
  onMark,
  onSeek,
  locked = false,
  pendingIds,
}: FindingsProps) {
  const open = findings.filter((f) => f.state === 'PROPOSED').length;
  const note = progressNote(open, findingsStatus);

  return (
    <section className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-4 sm:p-5">
      <div className="border-border-base flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b pb-4">
        <h2 className="text-ink text-[15px] font-semibold">확인할 내용</h2>
        <span className="bg-surface-bright text-ink-muted rounded-full px-2 py-0.5 font-mono text-[12px]">
          {findings.length}
        </span>
        {note && <span className="text-ink-dim text-[13px]">{note}</span>}
      </div>

      {locked && (
        <p className="text-ink-muted mt-3 text-xs">
          검토가 완료된 상태에서는 포함 여부를 바꿀 수 없습니다.
        </p>
      )}
      {coverage.length > 0 && (
        <ul aria-label="역량 커버리지" className="mt-4 flex flex-wrap gap-2">
          {coverage.map((c) => (
            <li
              key={c.name}
              className={`rounded-full border px-3 py-1 text-[13px] ${COVERAGE_STYLE[c.state]}`}
            >
              {c.name} · {coverageLabel(c.state, findingsStatus)}
            </li>
          ))}
        </ul>
      )}

      {findingsStatus === 'FAILED' ? (
        <p role="status" className="text-warning mt-4 text-[15px]">
          확인할 내용을 정리하지 못했습니다. 녹화와 문답으로 확인해 주세요.
        </p>
      ) : findings.length === 0 ? (
        <p className="text-ink-muted mt-4 text-[15px]">확인할 항목이 없습니다.</p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {findings.map((f) => (
            <li
              key={f.id}
              className={`rounded-xl border p-4 ${
                f.state === 'ADOPTED'
                  ? 'border-accent/40 bg-accent-tint/40'
                  : f.state === 'REJECTED'
                    ? 'border-border-base bg-surface-container opacity-60'
                    : 'border-border-base bg-surface-panel'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="bg-brand-tint text-brand-strong rounded-md px-2 py-0.5 text-[12px] font-semibold">
                  {FINDING_LABEL[f.type]}
                </span>
                {f.competency && <span className="text-ink-muted text-[13px]">{f.competency}</span>}
                <span className="flex-1" />
              </div>
              <p className="text-ink mt-3 text-[15px] leading-relaxed">{f.rationale}</p>
              <RecordExcerpt
                source={f.source}
                quote={f.quote}
                transcript={f.transcript}
                atSec={f.atSec}
                onSeek={onSeek}
              />

              <div className="mt-3 flex flex-wrap items-center gap-2">
                {f.state === 'PROPOSED' ? (
                  <>
                    <button
                      type="button"
                      disabled={locked || pendingIds?.has(f.id)}
                      onClick={() => onMark(f.id, 'ADOPTED')}
                      className="bg-brand hover:bg-brand-strong rounded-lg px-3 py-1.5 text-[13px] font-semibold text-white"
                    >
                      리포트에 포함
                    </button>
                    <button
                      type="button"
                      disabled={locked || pendingIds?.has(f.id)}
                      onClick={() => onMark(f.id, 'REJECTED')}
                      className="border-border-base bg-surface-panel text-ink hover:bg-surface-bright rounded-lg border px-3 py-1.5 text-[13px] font-medium"
                    >
                      제외
                    </button>
                  </>
                ) : (
                  <>
                    <span className="text-ink-muted text-[13px]">
                      {f.state === 'ADOPTED' ? '포함함' : '제외함'}
                    </span>
                    <button
                      type="button"
                      disabled={locked || pendingIds?.has(f.id)}
                      onClick={() => onMark(f.id, 'PROPOSED')}
                      className="text-ink-muted hover:text-ink -my-1 py-1 text-[13px] underline"
                    >
                      선택 취소
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
