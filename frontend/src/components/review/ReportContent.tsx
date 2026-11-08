import { FINDING_LABEL } from '../../lib/reviewLabels';
import type { ReportDocument, ReportStatement } from '../../types/report';
import { RecordExcerpt } from './RecordExcerpt';

const FINDING_ICON: Record<ReportStatement['findingType'], string> = {
  COMPETENCY_EVIDENCE: 'record_voice_over',
  CLAIM_VERIFIED: 'check_circle',
  CLAIM_CONTRADICTED: 'compare_arrows',
  CLAIM_UNVERIFIED: 'help',
  GAP: 'question_mark',
};

function Statements({ title, items }: { title: string; items: ReportStatement[] }) {
  if (!items.length) return null;
  return (
    <div className="mt-4">
      <h4 className="text-ink text-sm font-semibold">{title}</h4>
      <ul className="mt-2 space-y-3">
        {items.map((statement, index) => (
          <li
            key={`${statement.findingId}-${index}`}
            className="border-border-base rounded-xl border p-3"
          >
            <span className="bg-brand-tint text-brand-strong inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[12px]">
              <span aria-hidden className="material-symbols-outlined text-[16px]">
                {FINDING_ICON[statement.findingType]}
              </span>
              {FINDING_LABEL[statement.findingType]}
            </span>
            <p className="text-ink mt-2 text-sm leading-relaxed">{statement.text}</p>
            <RecordExcerpt {...statement} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReportContent({ report }: { report: ReportDocument }) {
  return (
    <article className="text-ink">
      <header className="border-border-base border-b pb-4">
        <h2 className="text-xl font-bold">
          {report.candidate.name || '이름 없는 지원자'} · 면접 리포트
        </h2>
        <p className="text-ink-muted mt-2 text-sm">
          {[
            `현재 설정 직무: ${report.candidate.role}`,
            report.interviewer.nickname,
            report.interviewedAt && new Date(report.interviewedAt).toLocaleString('ko-KR'),
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      </header>
      <section className="bg-surface-bright mt-5 rounded-xl p-4">
        <h3 className="font-semibold">면접관 메모</h3>
        <p className="text-ink-muted mt-2 text-sm leading-relaxed whitespace-pre-wrap">
          {report.memo || '작성된 메모가 없습니다.'}
        </p>
      </section>
      <section className="mt-5">
        <h3 className="font-semibold">면접 요약</h3>
        <p className="text-ink-muted mt-2 text-sm leading-relaxed whitespace-pre-wrap">
          {report.overview}
        </p>
      </section>
      <div className="mt-5 space-y-4">
        {report.competencies.map((competency, index) => (
          <section
            key={`${competency.name}-${index}`}
            className={`border-border-base rounded-xl border p-4 ${competency.state === 'MISSING' ? 'bg-surface-bright' : 'bg-surface-panel'}`}
          >
            <h3 className="flex flex-wrap items-center gap-2 font-semibold">
              {competency.name}
              <span className="text-ink-muted text-xs font-normal">
                {competency.required ? '필수' : '우대'}
              </span>
            </h3>
            {competency.state === 'MISSING' ? (
              <p className="text-ink-muted mt-3 flex items-center gap-1 text-sm">
                <span aria-hidden className="material-symbols-outlined text-[16px]">
                  question_mark
                </span>
                이번 면접에서 다루지 않음
              </p>
            ) : (
              <>
                <Statements title="확인된 점" items={competency.confirmed} />
                <Statements title="확인되지 않은 점" items={competency.unconfirmed} />
              </>
            )}
            {competency.nextQuestions.length > 0 && (
              <div className="mt-4">
                <h4 className="text-sm font-semibold">다음에 물어볼 것</h4>
                <ul className="text-ink-muted mt-2 list-disc space-y-2 pl-5 text-sm">
                  {competency.nextQuestions.map((question, i) => (
                    <li key={i}>{question}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        ))}
      </div>
      <footer className="border-border-base text-ink-dim mt-6 border-t pt-4 text-xs leading-relaxed">
        IRYA가 면접관이 선택한 내용을 정리했습니다. 평가 점수가 아닙니다.
      </footer>
    </article>
  );
}
