/**
 * 면접 요약 — 종료 후 화면 (이슈 #6)
 *
 * 요약은 면접이 끝난 뒤에 본다. 실시간 통로가 필요 없고 HTTP 조회 하나면 된다.
 *
 * LLM 요약은 즉시 나오지 않으므로 생성 중 상태를 거친다.
 * 서버가 PROCESSING 을 돌려주는 동안 화면이 주기적으로 다시 조회한다.
 *
 * 상태와 내용은 GET /sessions/{sessionId}/summary의 서버 응답을 그대로 따른다.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { getSessionState, getSummary } from '../api/interview';
import { ApiError } from '../api/client';
import { buttonClass } from '../components/ui/buttonClass';
import { Card } from '../components/ui/Card';
import { fmt } from '../lib/format';
import type { SummaryFailureReason } from '../types/interview';
import { failureMessage, latePollInterval } from '../lib/summaryState';

/** 생성 중일 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 2000;

export default function InterviewSummaryPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const {
    data: summary,
    isError,
    error,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['summary', sessionId],
    queryFn: () => getSummary(sessionId!),
    // sessionId 가 없으면 조회할 대상이 없다.
    enabled: Boolean(sessionId),
    // 생성이 끝날 때까지 되묻는다. 실패로 보여도 늦은 결과가 올 수 있으면 천천히
    // 더 묻는다 (`lib/summaryState.ts`). READY 면 멈춘다.
    refetchInterval: (q) => {
      const data = q.state.data;
      if (data?.status === 'PROCESSING') return POLL_INTERVAL_MS;
      if (data?.status === 'FAILED')
        return latePollInterval(data.failureReason, q.state.dataUpdateCount);
      return false;
    },
  });

  // 지금까지 받은 응답 수. 실패 뒤 얼마나 더 기다렸는지 센다 — 응답마다 다시 그려진다.
  const summaryChecks =
    useQueryClient().getQueryState(['summary', sessionId])?.dataUpdateCount ?? 0;

  // 면접 기록은 면접(interview) 단위라 세션에서 interviewId 를 얻어 온다.
  const {
    data: session,
    isError: sessionError,
    error: sessionErrorValue,
    isFetching: sessionFetching,
    refetch: refetchSession,
  } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSessionState(sessionId!),
    enabled: Boolean(sessionId),
  });
  const reviewPath = session ? `/review/${session.interviewId}` : null;

  const failed = isError;
  // 404 는 없는 세션이거나 남의 세션이다 (#145). 기다린다고 생기지 않으므로
  // 「잠시 후 다시」가 아니라 링크·계정을 확인하라고 안내한다.
  const missing = error instanceof ApiError && error.status === 404;
  // 세션 조회의 404 는 **없는 세션뿐**이다 — `GET /sessions/{id}` 는 주인을 보지 않아
  // 남의 세션도 200 을 준다. 그래도 기다려서 생기는 건 아니라 「다시 확인」은 감춘다.
  const sessionMissing = sessionErrorValue instanceof ApiError && sessionErrorValue.status === 404;
  const processing = !failed && (summary === undefined || summary.status === 'PROCESSING');

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pt-10 pb-12 sm:px-6">
      <div className="text-center">
        <span
          aria-hidden
          className="material-symbols-outlined bg-accent-tint text-accent-strong rounded-full p-3 text-[30px]"
        >
          task_alt
        </span>
        <h1 className="text-ink mt-4 text-[26px] font-bold tracking-tight">
          면접이 종료되었습니다
        </h1>
        {summary?.status === 'READY' && (
          <p className="text-ink-muted mt-1.5 text-[15px]">진행 시간 {fmt(summary.durationSec)}</p>
        )}
      </div>

      {processing && (
        <Card className="mt-8" aria-live="polite">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="border-brand-tint border-t-brand h-5 w-5 animate-spin rounded-full border-[3px]"
            />
            <p className="text-ink text-[16px] font-semibold">요약을 만들고 있습니다</p>
          </div>
          <p className="text-ink-muted mt-2 text-[14px] leading-relaxed">
            잠시만 기다려주세요. 이 화면을 벗어나도 나중에 결과를 다시 확인할 수 있습니다.
          </p>
          {/* 진행 표시 — 완료 시점을 알 수 없으므로 좌우로 오가는 막대로 둔다 */}
          <div className="bg-surface-bright mt-4 h-1.5 overflow-hidden rounded-full">
            <div className="bg-brand h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full" />
          </div>
        </Card>
      )}

      {failed && (
        <Card className="mt-8">
          <p className="text-warning text-[16px] font-semibold">
            {missing ? '없거나 볼 수 없는 면접입니다.' : '요약을 불러오지 못했습니다.'}
          </p>
          <p className="text-ink-muted mt-1.5 text-[14px] leading-relaxed">
            {missing
              ? '링크가 올바른지, 이 면접을 만든 계정으로 로그인했는지 확인해주세요.'
              : '네트워크를 확인한 뒤 다시 시도해주세요.'}
          </p>
          {!missing && (
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="text-brand mt-3 text-[14px] font-semibold disabled:opacity-50"
            >
              다시 확인
            </button>
          )}
        </Card>
      )}

      {!failed && summary?.status === 'FAILED' && (
        <FailedSummary
          reason={summary.failureReason}
          waiting={Boolean(latePollInterval(summary.failureReason, summaryChecks))}
        />
      )}

      {summary?.status === 'READY' && summary.content && (
        <Card className="mt-8">
          <h2 className="text-ink text-[17px] font-semibold">전체 요약</h2>
          <p className="text-ink/85 mt-3 text-[15px] leading-relaxed">{summary.content.overview}</p>

          <h2 className="text-ink border-border-base mt-6 border-t pt-5 text-[17px] font-semibold">
            핵심 내용
          </h2>
          <ul className="mt-3 flex flex-col gap-2.5">
            {summary.content.keyPoints.map((point) => (
              <li key={point} className="text-ink/85 flex gap-3 text-[15px] leading-relaxed">
                <span aria-hidden className="bg-brand mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full" />
                {point}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:justify-center">
        {sessionError && !sessionMissing && (
          <button
            type="button"
            onClick={() => void refetchSession()}
            disabled={sessionFetching}
            className={buttonClass('secondary')}
          >
            기록 링크 다시 확인
          </button>
        )}
        {/*
          요약이 실패해도 녹화와 기록은 따로 만들어지므로 기록으로 가는 길은 열어 둔다.
          단 missing 은 다르다 — 남의 세션이면 세션 조회가 200 이라 reviewPath 가 생기는데,
          기록 조회는 주인만 보므로 눌러도 똑같이 거절된다. "볼 수 없는 면접"이라고
          말한 화면에 같은 거절로 가는 주 버튼을 남기면 안 된다 (#150).
        */}
        {reviewPath && !missing && (
          <Link to={reviewPath} className={buttonClass('primary')}>
            면접 기록 보기
            <span aria-hidden className="material-symbols-outlined text-[20px]">
              arrow_forward
            </span>
          </Link>
        )}
        <Link to="/" className={buttonClass('secondary')}>
          홈으로
        </Link>
      </div>
    </div>
  );
}

/** 요약이 실패로 보일 때. 늦게 올 수 있으면 기다리는 중임을 함께 보여 준다. */
function FailedSummary({
  reason,
  waiting,
}: {
  reason: SummaryFailureReason | null;
  waiting: boolean;
}) {
  const { title, detail } = failureMessage(reason, waiting);
  return (
    <Card className="mt-8" aria-live="polite">
      <div className="flex items-center gap-3">
        {waiting ? (
          <span
            aria-hidden
            className="border-brand-tint border-t-brand h-5 w-5 shrink-0 animate-spin rounded-full border-[3px]"
          />
        ) : (
          <span aria-hidden className="text-warning">
            <span className="material-symbols-outlined text-[22px]">
              {reason === 'NO_TRANSCRIPT' ? 'mic_off' : 'error'}
            </span>
          </span>
        )}
        <p className={`text-[16px] font-semibold ${waiting ? 'text-ink' : 'text-warning'}`}>
          {title}
        </p>
      </div>
      <p className="text-ink-muted mt-2 text-[14px] leading-relaxed">{detail}</p>
    </Card>
  );
}
