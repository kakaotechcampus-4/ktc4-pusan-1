/**
 * 검토 항목과 역량 커버리지 (#137 1-2 · 1-4).
 *
 * AI 가 근거와 함께 짚은 것을 면접관이 채택하거나 반려한다. 판정이 아니므로 AI 의
 * 말투로 결론을 적지 않고, 근거(지원서 문장 · 면접 발화)를 그대로 보여 준다.
 */

import { fmt } from '../../lib/format';
import type { Coverage, Finding } from '../../types/interview';

const TYPE_LABEL: Record<Finding['type'], string> = {
  COMPETENCY_EVIDENCE: '역량 근거',
  CLAIM_VERIFIED: '지원서와 일치',
  CLAIM_CONTRADICTED: '지원서와 다름',
  CLAIM_UNVERIFIED: '확인 안 됨',
  GAP: '질문 안 됨',
};

const COVERAGE_LABEL: Record<Coverage['state'], string> = {
  CONFIRMED: '확인',
  PARTIAL: '일부',
  MISSING: '없음',
};

const COVERAGE_STYLE: Record<Coverage['state'], string> = {
  CONFIRMED: 'border-accent/30 bg-accent-tint text-accent-strong',
  PARTIAL: 'border-warning/30 bg-warning-tint text-warning',
  MISSING: 'border-border-base bg-surface-bright text-ink-dim',
};

export interface FindingsProps {
  coverage: Coverage[];
  findings: Finding[];
  onMark: (findingId: string, state: Finding['state']) => void;
  onSeek: (sec: number) => void;
}

export function Findings({ coverage, findings, onMark, onSeek }: FindingsProps) {
  const open = findings.filter((f) => f.state === 'PROPOSED').length;

  return (
    <section className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-4 sm:p-5">
      <div className="border-border-base flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b pb-4">
        <h2 className="text-ink text-[15px] font-semibold">검토 항목</h2>
        <span className="bg-surface-bright text-ink-muted rounded-full px-2 py-0.5 font-mono text-[12px]">
          {findings.length}
        </span>
        <span className="text-ink-dim text-[13px]">
          {open > 0 ? `${open}건이 아직 판단 전입니다` : '모두 판단했습니다'}
        </span>
      </div>

      {coverage.length > 0 && (
        <ul aria-label="역량 커버리지" className="mt-4 flex flex-wrap gap-2">
          {coverage.map((c) => (
            <li
              key={c.name}
              className={`rounded-full border px-3 py-1 text-[13px] ${COVERAGE_STYLE[c.state]}`}
            >
              {c.name} · {COVERAGE_LABEL[c.state]}
            </li>
          ))}
        </ul>
      )}

      {findings.length === 0 ? (
        <p className="text-ink-muted mt-4 text-[15px]">AI 가 짚은 항목이 없습니다.</p>
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
                  {TYPE_LABEL[f.type]}
                </span>
                {f.competency && <span className="text-ink-muted text-[13px]">{f.competency}</span>}
                <span className="flex-1" />
                {f.atSec !== null && (
                  <button
                    type="button"
                    onClick={() => onSeek(f.atSec!)}
                    className="border-border-base text-ink-muted hover:text-ink rounded-full border px-2.5 py-0.5 font-mono text-[12px]"
                    aria-label={`${fmt(f.atSec)} 로 이동`}
                  >
                    {fmt(f.atSec)}
                  </button>
                )}
              </div>

              <p className="text-ink/85 mt-3 text-[15px] leading-relaxed">{f.rationale}</p>

              {f.quote && (
                <p className="border-border-base text-ink-muted mt-3 border-l-2 pl-3 text-[13px] leading-relaxed">
                  <span className="text-ink-dim">{f.source ?? '지원서'} · </span>“{f.quote}”
                </p>
              )}
              {f.transcript && (
                <p className="border-brand/40 text-ink-muted mt-2 border-l-2 pl-3 text-[13px] leading-relaxed">
                  <span className="text-ink-dim">면접 답변 · </span>“{f.transcript}”
                </p>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                {f.state === 'PROPOSED' ? (
                  <>
                    <button
                      type="button"
                      onClick={() => onMark(f.id, 'ADOPTED')}
                      className="bg-brand hover:bg-brand-strong rounded-lg px-3 py-1.5 text-[13px] font-semibold text-white"
                    >
                      근거로 채택
                    </button>
                    <button
                      type="button"
                      onClick={() => onMark(f.id, 'REJECTED')}
                      className="border-border-base bg-surface-panel text-ink hover:bg-surface-bright rounded-lg border px-3 py-1.5 text-[13px] font-medium"
                    >
                      반려
                    </button>
                  </>
                ) : (
                  <>
                    <span className="text-ink-muted text-[13px]">
                      {f.state === 'ADOPTED' ? '채택함' : '반려함'}
                    </span>
                    <button
                      type="button"
                      onClick={() => onMark(f.id, 'PROPOSED')}
                      className="text-ink-muted hover:text-ink text-[13px] underline"
                    >
                      되돌리기
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
