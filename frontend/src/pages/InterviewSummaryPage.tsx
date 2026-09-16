/**
 * 면접 요약 — 종료 후 화면 (이슈 #6)
 *
 * 요약은 면접이 끝난 뒤에 본다. 실시간 통로가 필요 없고 HTTP 조회 하나면 된다.
 *
 * LLM 요약은 즉시 나오지 않으므로 생성 중 상태를 거친다.
 * 서버가 PROCESSING 을 돌려주는 동안 화면이 주기적으로 다시 조회한다.
 *
 * ⚠️ 이 엔드포인트는 아직 명세에 없다. 출력 형식도 #6 에서 정의될 예정이라
 * 지금 구조(overview + keyPoints)는 FE 제안이다.
 */

import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { getSummary } from '../api/interview';
import { fmt } from '../lib/format';

/** 생성 중일 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 2000;

export default function InterviewSummaryPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { data: summary, isError } = useQuery({
    queryKey: ['summary', sessionId],
    queryFn: () => getSummary(sessionId!),
    // sessionId 가 없으면 조회할 대상이 없다.
    enabled: Boolean(sessionId),
    // 생성이 끝날 때까지 되묻는다. 완료되면 false 를 돌려 폴링을 멈춘다.
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? POLL_INTERVAL_MS : false),
  });

  const failed = isError;
  const processing = !failed && (summary === undefined || summary.status === 'PROCESSING');

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-2xl">
        <h1 className="text-2xl font-semibold text-white">면접이 종료되었습니다</h1>

        {processing && (
          <div aria-live="polite" className="mt-7 rounded-xl bg-white/[0.06] p-6">
            <p className="text-[15px] text-white">요약을 만들고 있습니다</p>
            <p className="mt-1.5 text-sm text-white/50">
              잠시만 기다려주세요. 이 화면을 벗어나도 요약은 계속 생성됩니다.
            </p>
            {/* 진행 표시 — 완료 시점을 알 수 없으므로 좌우로 오가는 막대로 둔다 */}
            <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/10">
              <div className="h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-[#2B44D6]" />
            </div>
          </div>
        )}

        {(failed || summary?.status === 'FAILED') && (
          <div className="mt-7 rounded-xl bg-white/[0.06] p-6">
            <p className="text-[15px] text-[#FFC46B]">요약을 만들지 못했습니다.</p>
            <p className="mt-1.5 text-sm leading-relaxed text-white/55">
              면접 기록은 남아 있습니다. 잠시 후 다시 확인해주세요.
            </p>
          </div>
        )}

        {summary?.status === 'READY' && summary.content && (
          <>
            <p className="mt-2 text-[15px] text-white/60">진행 시간 {fmt(summary.durationSec)}</p>

            <section className="mt-7 rounded-xl bg-white/[0.06] p-6">
              <h2 className="text-[15px] font-semibold text-white">전체 요약</h2>
              <p className="mt-3 text-[15px] leading-relaxed text-white/80">
                {summary.content.overview}
              </p>
            </section>

            <section className="mt-4 rounded-xl bg-white/[0.06] p-6">
              <h2 className="text-[15px] font-semibold text-white">핵심 내용</h2>
              <ul className="mt-3 flex flex-col gap-2.5">
                {summary.content.keyPoints.map((point) => (
                  <li key={point} className="flex gap-3 text-[15px] leading-relaxed text-white/80">
                    <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[#7A97FF]" />
                    {point}
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}

        <Link
          to="/"
          className="mt-7 inline-block rounded-lg bg-white/[0.08] px-5 py-3 text-[15px] font-medium text-white transition hover:bg-white/[0.13]"
        >
          처음으로
        </Link>
      </div>
    </div>
  );
}
