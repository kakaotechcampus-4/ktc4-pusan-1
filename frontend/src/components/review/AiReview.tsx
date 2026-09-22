/**
 * AI 평가. 합격 여부는 판단하지 않고, 근거가 된 자료만 서술한다.
 */

export function AiReview({ paragraphs }: { paragraphs: string[] }) {
  return (
    <section className="border-border-base bg-surface-panel rounded-2xl border p-4 sm:p-5">
      <div className="border-border-base flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b pb-4">
        <span aria-hidden className="bg-brand-soft h-1.5 w-1.5 rounded-full" />
        <h2 className="text-ink text-[15px] font-semibold">AI 평가</h2>
        <span className="text-ink-dim text-[13px]">전사 · 지원서 · JD 를 근거로 작성</span>
      </div>

      <div className="mt-4 flex flex-col gap-3">
        {paragraphs.map((p, i) => (
          // 문단은 순서가 곧 정체성이고 재정렬되지 않는다.
          <p key={i} className="text-ink/85 text-[15px] leading-[1.75]">
            {p}
          </p>
        ))}
      </div>

      <p className="border-border-base text-ink-dim mt-4 border-t pt-4 text-[13px] leading-relaxed">
        합격 여부는 판단하지 않습니다. 위 내용은 면접에서 실제로 나온 말과 지원서에 적힌 내용만을
        근거로 합니다.
      </p>
    </section>
  );
}
