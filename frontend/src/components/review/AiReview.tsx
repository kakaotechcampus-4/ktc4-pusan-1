/**
 * AI 평가. 합격 여부는 판단하지 않고, 근거가 된 자료만 서술한다.
 *
 * 요약이 없을 수 있다 — 한도를 넘기면 서버가 FAILED 로 준다. 그때 빈 칸을 두면
 * 「AI 가 할 말이 없었다」로 읽히므로, 왜 비었는지를 적는다.
 */

import type { SummaryContent, SummaryStatus } from '../../types/interview';

export interface AiReviewProps {
  summary: SummaryContent | null;
  status: SummaryStatus;
}

export function AiReview({ summary, status }: AiReviewProps) {
  return (
    <section className="border-border-base bg-surface-panel rounded-2xl border p-4 sm:p-5">
      <div className="border-border-base flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b pb-4">
        <span aria-hidden className="bg-brand-soft h-1.5 w-1.5 rounded-full" />
        <h2 className="text-ink text-[15px] font-semibold">AI 평가</h2>
        <span className="text-ink-dim text-[13px]">전사 · 지원서 · JD 를 근거로 작성</span>
      </div>

      {summary ? (
        <div className="mt-4 flex flex-col gap-4">
          <p className="text-ink/85 text-[15px] leading-[1.75]">{summary.overview}</p>

          {summary.keyPoints.length > 0 && (
            <ul className="flex flex-col gap-2">
              {summary.keyPoints.map((point) => (
                // 핵심은 문장이 곧 식별자다. 같은 문장이 두 번 올 이유가 없다.
                <li key={point} className="text-ink/85 flex gap-2.5 text-[15px] leading-[1.7]">
                  <span aria-hidden className="text-brand-soft">
                    ·
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-ink-muted mt-4 text-[15px] leading-relaxed">
          {status === 'FAILED'
            ? '요약을 만들지 못했습니다. 아래 문답과 녹화로 검토할 수 있습니다.'
            : '요약을 만들고 있습니다.'}
        </p>
      )}

      <p className="border-border-base text-ink-dim mt-4 border-t pt-4 text-[13px] leading-relaxed">
        합격 여부는 판단하지 않습니다. 위 내용은 면접에서 실제로 나온 말과 지원서에 적힌 내용만을
        근거로 합니다.
      </p>
    </section>
  );
}
