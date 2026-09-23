/**
 * 면접 기록 — 리뷰 타임라인 (S3)
 *
 * 끝난 면접의 녹화를 다시 본다. 타임라인이나 목록에서 질문을 고르면 영상이 그 시점으로
 * 이동하고, 그 문답이 영상 위에 겹쳐 보인다.
 *
 * 녹화 변환과 AI 평가에 시간이 걸리므로 준비 중 상태를 거친다.
 *
 * ⚠️ BE 에 이 엔드포인트가 없어 목으로 동작한다.
 */

import { useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getReview } from '../api/review';
import { AiReview } from '../components/review/AiReview';
import { QaList } from '../components/review/QaList';
import { ReviewPlayer } from '../components/review/ReviewPlayer';
import { Timeline } from '../components/review/Timeline';
import { useHlsPlayer } from '../hooks/useHlsPlayer';
import { fmt } from '../lib/format';
import type { Moment } from '../types/interview';

/** 준비 중일 때 다시 물어보는 간격 */
const POLL_INTERVAL_MS = 3000;

export default function ReviewTimelinePage() {
  const { interviewId } = useParams<{ interviewId: string }>();
  const { data, isError } = useQuery({
    queryKey: ['review', interviewId],
    queryFn: () => getReview(interviewId!),
    enabled: Boolean(interviewId),
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? POLL_INTERVAL_MS : false),
  });

  const review = data?.status === 'READY' ? data : undefined;
  const { videoRef, seekTo, failed } = useHlsPlayer(review?.recording.hlsUrl);

  // 처음에는 아무것도 고르지 않는다. 미리 골라 두면 영상은 00:00 인데 오버레이는
  // 다른 시점의 문답을 보여주는 어긋난 상태로 시작한다.
  const [activeId, setActiveId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(true);

  const activeIndex = review?.moments.findIndex((m) => m.id === activeId) ?? -1;
  const active = activeIndex >= 0 ? review?.moments[activeIndex] : undefined;

  const select = (moment: Moment) => {
    setActiveId(moment.id);
    seekTo(moment.atSec);
  };

  if (isError) {
    return (
      <Centered>
        <p className="text-[15px] text-[#FFC46B]">면접 기록을 불러오지 못했습니다.</p>
        <p className="text-ink-muted mt-1.5 text-sm">잠시 후 다시 확인해주세요.</p>
        <HomeLink />
      </Centered>
    );
  }

  if (!review) {
    const etaSec = data?.status === 'PROCESSING' ? data.etaSec : undefined;
    return (
      <Centered>
        <div
          aria-live="polite"
          className="border-border-base bg-surface-panel rounded-2xl border p-6"
        >
          <p className="text-ink text-[15px]">면접 기록을 정리하고 있습니다</p>
          <p className="text-ink-muted mt-1.5 text-sm">
            녹화를 변환하고 AI 평가를 만드는 중입니다.
            {etaSec ? ` 약 ${Math.ceil(etaSec / 60)}분 남았습니다.` : ''}
          </p>
          <div className="bg-surface-bright mt-4 h-1 overflow-hidden rounded-full">
            <div className="bg-brand h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full" />
          </div>
        </div>
      </Centered>
    );
  }

  return (
    <div className="bg-surface min-h-full px-4 py-6 sm:px-6 md:px-10 md:py-8">
      <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-3">
        <header className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="min-w-0">
            <p className="text-ink-dim text-[13px]">면접 기록</p>
            <h1 className="text-ink mt-1 text-2xl font-semibold">{review.candidate.name}</h1>
          </div>
          <span className="text-ink-muted pb-1 font-mono text-[13px]">
            {review.candidate.role} · {fmt(review.durationSec)}
          </span>
          <span className="flex-1" />
          {/* 지원자 목록(S4)이 아직 없어 처음으로 돌아간다. */}
          <Link
            to="/"
            className="bg-brand hover:bg-brand/85 rounded-lg px-5 py-3 text-[15px] font-medium text-white transition"
          >
            정리 마치기
          </Link>
        </header>

        {/* 이 화면이 무엇을 하는 곳인지 먼저 적는다 — 시안의 첫 줄이다. */}
        <p className="text-ink-muted text-[13px] leading-relaxed">
          이 화면은 지원자를 평가하지 않습니다. 질문과 답변을 원본 영상의 위치에 연결해 두었습니다.
          판단은 면접관이 합니다.
        </p>

        <ReviewPlayer
          videoRef={videoRef}
          active={active}
          activeNo={activeIndex + 1}
          candidateName={review.candidate.name}
          durationSec={review.durationSec}
          failed={failed}
        />

        <Timeline
          moments={review.moments}
          durationSec={review.durationSec}
          activeId={activeId}
          onSelect={select}
        />

        <QaList
          moments={review.moments}
          activeId={activeId}
          onSelect={select}
          open={listOpen}
          onToggle={() => setListOpen((v) => !v)}
        />

        <AiReview paragraphs={review.aiReview.paragraphs} />
      </div>
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="bg-surface flex min-h-full items-center justify-center p-8">
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}

function HomeLink() {
  return (
    <Link
      to="/"
      className="border-border-base bg-surface-bright text-ink hover:bg-surface-container mt-6 inline-block rounded-lg border px-5 py-3 text-[15px] font-medium transition"
    >
      처음으로
    </Link>
  );
}
