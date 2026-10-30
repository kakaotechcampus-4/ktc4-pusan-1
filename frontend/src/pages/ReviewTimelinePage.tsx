/**
 * 면접 기록 — 리뷰 타임라인 (S3)
 *
 * 끝난 면접의 녹화를 다시 본다. 타임라인이나 목록에서 질문을 고르면 영상이 그 시점으로
 * 이동하고, 그 문답이 영상 위에 겹쳐 보인다.
 *
 * 녹화는 상세 응답에 실리지 않고 `sessionId` 로 따로 받는다 (#112) — 서명 URL 이
 * 10분 만에 만료돼서 상세와 같이 캐시해 두면 다시 열 때 죽은 주소가 된다.
 *
 * 녹화가 없는 면접도 여기서 검토한다. 문답과 요약은 녹화와 무관하게 그린다.
 *
 * 넓은 화면은 왼쪽에 영상 · 타임라인 · 문답, 오른쪽에 AI 검토 · 메모를 둔다. 좁은 화면은
 * 세 묶음을 탭으로 나눈다. 검토 상태는 화면 아래 막대에 붙어 있다 (#232).
 *
 * 채택 · 북마크는 응답을 기다리지 않고 상세 캐시에 먼저 반영한다. 실패하면 그 항목만
 * 되돌린다 (`lib/reviewMarks.ts`).
 */

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getReview, putMark } from '../api/review';
import { ApiError } from '../api/client';
import { getInterview } from '../api/interview';
import { getRecording } from '../api/recording';
import { AiReview } from '../components/review/AiReview';
import { Findings } from '../components/review/Findings';
import { QaList } from '../components/review/QaList';
import { ReviewNotes } from '../components/review/ReviewNotes';
import { ReviewPlayer } from '../components/review/ReviewPlayer';
import { ReviewStatusBar } from '../components/review/ReviewStatusBar';
import { Timeline } from '../components/review/Timeline';
import { ReportPanel } from '../components/review/ReportPanel';
import { useRecordingPlayer } from '../hooks/useRecordingPlayer';
import { FALLBACK_CANDIDATE } from '../lib/candidateName';
import { Badge } from '../components/ui/Badge';
import { buttonClass } from '../components/ui/buttonClass';
import { fmt } from '../lib/format';
import { STATUS_LABEL, STATUS_TONE } from '../lib/interviewList';
import { latePollInterval } from '../lib/summaryState';
import { applyMark, currentMark } from '../lib/reviewMarks';
import type { MarkUpdate, Moment, Review, ReviewResponse } from '../types/interview';

type Tab = 'record' | 'ai' | 'memo';
const TABS: { id: Tab; label: string }[] = [
  { id: 'record', label: '영상 · 문답' },
  { id: 'ai', label: '면접 요약' },
  { id: 'memo', label: '메모' },
];

/** 준비 중일 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 3000;

export default function ReviewTimelinePage() {
  const { interviewId } = useParams<{ interviewId: string }>();
  const { data, isError, error, isFetching, refetch } = useQuery({
    queryKey: ['review', interviewId],
    queryFn: () => getReview(interviewId!),
    enabled: Boolean(interviewId),
    // 준비 중이면 자주, 요약만 실패로 보이면 늦은 결과를 천천히 기다린다
    // (`lib/summaryState.ts`). 다시 받아도 메모 칸은 자기 글을 들고 있어 밀리지 않는다.
    refetchInterval: (q) => {
      const d = q.state.data;
      if (d?.status === 'PROCESSING') return POLL_INTERVAL_MS;
      if (d?.status === 'READY' && d.summaryStatus === 'FAILED')
        return latePollInterval(d.failureReason, q.state.dataUpdateCount);
      return false;
    },
  });
  // 실패 뒤 얼마나 더 기다렸는지 — AI 평가 카드가 「늦어진다 / 실패했다」를 고른다.
  const queryClient = useQueryClient();
  const reviewChecks = queryClient.getQueryState(['review', interviewId])?.dataUpdateCount ?? 0;

  // 기록이 준비 중이어도 어떤 지원자의 면접인지 실제 면접 조회로 확인한다.
  const { data: interview, refetch: refetchInterview } = useQuery({
    queryKey: ['interview', interviewId],
    queryFn: () => getInterview(interviewId!),
    enabled: Boolean(interviewId),
  });

  const review = data?.status === 'READY' ? data : undefined;
  const sessionId = review?.sessionId;

  // 녹화는 상세와 따로 받는다. 상세가 READY 가 되기 전에는 부를 세션이 없다.
  // 주소를 다시 받으면 `<video>` 의 src 가 바뀌어 재생 위치가 0 으로 돌아가므로,
  // 합치는 중일 때만 다시 묻고 READY 가 되면 멈춘다.
  const { data: recording, isError: recordingError } = useQuery({
    queryKey: ['recording', sessionId],
    queryFn: () => getRecording(sessionId!),
    enabled: Boolean(sessionId),
    refetchOnReconnect: false,
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? POLL_INTERVAL_MS : false),
  });

  const playable = recording?.status === 'READY' ? recording : undefined;
  // 녹화가 없으면 보정할 것도 없다. 0 이면 전사 시각이 그대로 재생 위치가 된다.
  const offsetMs = playable?.offsetMs ?? 0;
  const { videoRef, seekTo, failed } = useRecordingPlayer(playable?.url, offsetMs);
  const recordingFailed = failed || (recordingError && !playable);

  // 처음에는 아무것도 고르지 않는다. 미리 골라 두면 영상은 00:00 인데 오버레이는
  // 다른 시점의 문답을 보여주는 어긋난 상태로 시작한다.
  const [activeId, setActiveId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(true);
  // 좁은 화면에서 보이는 묶음. 넓은 화면은 셋을 한꺼번에 보여 주므로 쓰지 않는다.
  const [tab, setTab] = useState<Tab>('record');

  const activeIndex = review?.moments.findIndex((m) => m.id === activeId) ?? -1;
  const active = activeIndex >= 0 ? review?.moments[activeIndex] : undefined;

  const select = (moment: Moment) => {
    setActiveId(moment.id);
    seekTo(moment.atSec);
  };

  // 표시를 저장하지 못했을 때 보여 줄 한 줄. 다시 눌러 되는 실패와 확정 때문에 막힌
  // 것을 구분한다 — 확정 뒤에는 다시 눌러도 같은 409 다 (#247).
  const [markFailed, setMarkFailed] = useState<string | null>(null);
  const patchReview = (change: Partial<Review> | ((r: Review) => Review)) =>
    queryClient.setQueryData<ReviewResponse>(['review', interviewId], (prev) =>
      prev?.status === 'READY'
        ? typeof change === 'function'
          ? { ...change(prev), status: 'READY' }
          : { ...prev, ...change }
        : prev,
    );

  const mark = (itemId: string, next: MarkUpdate) => {
    const before = review && currentMark(review, itemId, next);
    if (!before) return;
    setMarkFailed(null);
    patchReview((r) => applyMark(r, itemId, next));
    putMark(interviewId!, itemId, next).catch((e: unknown) => {
      patchReview((r) => applyMark(r, itemId, before));
      const locked = e instanceof ApiError && e.code === 'REVIEW_CONFIRMED';
      setMarkFailed(
        locked
          ? '검토가 확정되어 바꾸지 못했습니다. 아래에서 「검토 중」으로 돌린 뒤 다시 눌러주세요.'
          : '표시를 저장하지 못해 되돌렸습니다. 다시 눌러주세요.',
      );
      // 다른 창에서 확정했을 수 있다 — 버튼도 같이 잠기게 상태를 다시 읽는다.
      if (locked) void queryClient.invalidateQueries({ queryKey: ['review', interviewId] });
    });
  };

  if (isError) {
    // 404 는 없는 면접이거나 남의 면접이다 (#145). 둘 다 기다린다고 달라지지 않으므로
    // 다시 확인을 권하지 않는다 — 어느 쪽인지는 서버가 일부러 구분해 주지 않는다.
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <Centered>
        {interview?.candidateName && (
          <h1 className="text-ink mb-4 text-xl font-semibold">
            {interview.candidateName} · 면접 기록
          </h1>
        )}
        <p className="text-warning text-[15px] font-semibold">
          {missing ? '없거나 볼 수 없는 면접입니다.' : '면접 기록을 불러오지 못했습니다.'}
        </p>
        <p className="text-ink-muted mt-1.5 text-sm">
          {missing
            ? '링크가 올바른지, 이 면접을 만든 계정으로 로그인했는지 확인해주세요.'
            : '잠시 후 다시 확인해주세요.'}
        </p>
        {!missing && (
          <button
            type="button"
            onClick={() => {
              void refetch();
              void refetchInterview();
            }}
            disabled={isFetching}
            className="text-brand mt-4 text-sm font-semibold disabled:opacity-50"
          >
            다시 확인
          </button>
        )}
        <HomeLink />
      </Centered>
    );
  }

  if (!review) {
    const etaSec = data?.status === 'PROCESSING' ? data.etaSec : undefined;
    return (
      <Centered>
        {interview?.candidateName && (
          <h1 className="text-ink mb-4 text-xl font-semibold">
            {interview.candidateName} · 면접 기록
          </h1>
        )}
        <div
          aria-live="polite"
          className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-6"
        >
          <p className="text-ink text-[15px]">면접 기록을 정리하고 있습니다</p>
          <p className="text-ink-muted mt-1.5 text-sm">
            면접 기록이 아직 준비되지 않았습니다. 이 화면을 나갔다가 다시 확인할 수 있습니다.
            {etaSec ? ` 약 ${Math.ceil(etaSec / 60)}분 남았습니다.` : ''}
          </p>
          <div className="bg-surface-bright mt-4 h-1 overflow-hidden rounded-full">
            <div className="bg-brand h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full" />
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            void refetch();
            void refetchInterview();
          }}
          disabled={isFetching}
          className="text-brand mt-4 text-sm font-semibold disabled:opacity-50"
        >
          다시 확인
        </button>
        <HomeLink />
      </Centered>
    );
  }

  // 이름을 비워 두고 만든 면접이 있다. 빈 칸으로 두면 제목이 사라진 것처럼 보인다.
  const candidateName = review.candidate.name ?? FALLBACK_CANDIDATE;
  // 전사 길이가 없으면(아무도 입장하지 않고 끝낸 면접) 녹화 길이로 대신 적는다.
  const durationSec = review.durationSec ?? playable?.durationSec ?? 0;
  // 불러오는 중과 합치는 중은 면접관이 할 일이 같다 — 기다리면 된다.
  const recordingState = recording?.status ?? 'PROCESSING';

  const openFindings = review.findings.filter((f) => f.state === 'PROPOSED').length;

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 pt-6 pb-36 sm:px-6 lg:px-8 lg:pb-28">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link
          to="/candidates"
          aria-label="지원자 목록으로"
          className="text-ink-muted hover:bg-surface-bright hover:text-ink -ml-2 rounded-lg p-2"
        >
          <span aria-hidden className="material-symbols-outlined text-[22px]">
            arrow_back
          </span>
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-ink truncate text-[22px] font-bold tracking-tight">
            {candidateName}
          </h1>
          <p className="text-ink-dim text-[13px]">
            {[review.candidate.role, fmt(durationSec), review.interviewer.nickname]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <Badge tone={STATUS_TONE[review.reviewStatus]}>{STATUS_LABEL[review.reviewStatus]}</Badge>
      </header>

      <div className="mt-4">
        <ReportPanel interviewId={interviewId!} compact />
      </div>

      {/* 이 화면이 무엇을 하는 곳인지 먼저 적는다 — 시안의 첫 줄이다. */}
      <p className="text-ink-muted mt-3 text-[13px] leading-relaxed">
        이 화면은 지원자를 평가하지 않습니다. 질문과 답변을 원본 영상의 위치에 연결해 두었습니다.
        판단은 면접관이 합니다.
      </p>

      {/* 좁은 화면 — 세 묶음을 탭으로 나눈다. 숨겨도 영상은 그대로 붙어 있어 재생이 끊기지 않는다. */}
      <div
        role="tablist"
        aria-label="면접 기록"
        className="bg-surface-bright mt-4 grid grid-cols-3 gap-1 rounded-xl p-1 lg:hidden"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg py-2 text-[14px] font-semibold transition ${
              tab === t.id ? 'bg-surface-panel text-ink shadow-card' : 'text-ink-muted'
            }`}
          >
            {t.label}
            {t.id === 'ai' && openFindings > 0 && (
              <span className="text-warning ml-1 tabular-nums">{openFindings}</span>
            )}
          </button>
        ))}
      </div>

      <div className="mt-4 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] lg:items-start lg:gap-6">
        <div className={`flex flex-col gap-4 ${tab === 'record' ? '' : 'hidden lg:flex'}`}>
          <ReviewPlayer
            videoRef={videoRef}
            active={active}
            activeNo={activeIndex + 1}
            candidateName={candidateName}
            durationSec={durationSec}
            recordingState={recordingState}
            failed={recordingFailed}
            offsetMs={offsetMs}
          />

          <Timeline
            moments={review.moments}
            durationSec={durationSec}
            activeId={activeId}
            onSelect={select}
            seekable={recordingState === 'READY' && !recordingFailed}
          />

          <QaList
            moments={review.moments}
            activeId={activeId}
            onSelect={select}
            onBookmark={(m) => mark(m.id, { bookmarked: !m.bookmarked })}
            open={listOpen}
            onToggle={() => setListOpen((v) => !v)}
          />
        </div>

        {/* 넓은 화면 — 오른쪽 열은 스크롤해도 따라온다. 길면 열 안에서 따로 스크롤한다. */}
        <aside className="flex flex-col gap-4 lg:sticky lg:top-6 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto lg:pb-1">
          <div className={`flex flex-col gap-4 ${tab === 'ai' ? '' : 'hidden lg:flex'}`}>
            <AiReview
              summary={review.summary}
              status={review.summaryStatus}
              failureReason={review.failureReason}
              waiting={Boolean(latePollInterval(review.failureReason, reviewChecks))}
            />

            {markFailed && (
              <p role="alert" className="text-danger text-[13px]">
                {markFailed}
              </p>
            )}

            <Findings
              coverage={review.coverage}
              findings={review.findings}
              findingsStatus={review.findingsStatus}
              onMark={(id, state) => mark(id, { state })}
              onSeek={seekTo}
              locked={review.reviewStatus === 'CONFIRMED'}
            />
          </div>

          <div className={tab === 'memo' ? '' : 'hidden lg:block'}>
            <ReviewNotes
              interviewId={review.interviewId}
              memo={review.memo}
              onSaved={patchReview}
            />
          </div>
        </aside>
      </div>

      <ReviewStatusBar
        interviewId={review.interviewId}
        reviewStatus={review.reviewStatus}
        reviewedAt={review.reviewedAt}
        openFindings={openFindings}
        findingsFailed={review.findingsStatus === 'FAILED'}
        onSaved={patchReview}
      />
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center p-8">
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}

function HomeLink() {
  return (
    <Link to="/candidates" className={`${buttonClass('secondary')} mt-6`}>
      지원자 목록으로
    </Link>
  );
}
