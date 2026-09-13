/**
 * AI 평가. 합격 여부는 판단하지 않고, 근거가 된 자료만 서술한다.
 */

export function AiReview({ paragraphs }: { paragraphs: string[] }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border-l-[3px] border-l-[#2B44D6] bg-white/[0.06] px-6 py-5">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#7A97FF]" />
        <h2 className="text-[15px] font-semibold text-white">AI 평가</h2>
        <span className="text-[13px] text-white/45">전사 · 지원서 · JD 를 근거로 작성</span>
      </div>

      {paragraphs.map((p, i) => (
        // 문단은 순서가 곧 정체성이고 재정렬되지 않는다.
        <p key={i} className="text-[15px] leading-[1.75] text-white/80">
          {p}
        </p>
      ))}

      <p className="border-t border-white/10 pt-3 text-[13px] leading-relaxed text-white/45">
        합격 여부는 판단하지 않습니다. 위 내용은 면접에서 실제로 나온 말과 지원서에 적힌 내용만을
        근거로 합니다.
      </p>
    </section>
  );
}
