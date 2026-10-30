import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { getInterview } from '../../api/interview';
import { getReview, putMark } from '../../api/review';
import { getRecording } from '../../api/recording';
import { useRecordingPlayer } from '../../hooks/useRecordingPlayer';
import { STATUS_LABEL, STATUS_TONE } from '../../lib/interviewList';
import { Badge } from '../ui/Badge';
import { Findings } from './Findings';
import { ReviewNotes } from './ReviewNotes';
import { ReportPanel } from './ReportPanel';
import type { Finding } from '../../types/interview';

function ComparisonRecording({ sessionId, atSec }: { sessionId: string; atSec: number }) {
  const recording = useQuery({
    queryKey: ['recording', sessionId],
    queryFn: () => getRecording(sessionId),
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? 3000 : false),
  });
  const ready = recording.data?.status === 'READY' ? recording.data : undefined;
  const { videoRef, seekTo, failed } = useRecordingPlayer(ready?.url, ready?.offsetMs ?? 0);
  const lastSeek = useRef<string | null>(null);
  useEffect(() => {
    const key = `${sessionId}:${atSec}`;
    if (ready && lastSeek.current !== key) {
      lastSeek.current = key;
      seekTo(atSec);
    }
  }, [ready, atSec, seekTo, sessionId]);
  if (recording.isError || failed)
    return (
      <p role="alert" className="text-danger text-sm">
        녹화를 재생하지 못했습니다.
      </p>
    );
  if (!ready)
    return (
      <p role="status" className="text-ink-muted text-sm">
        {recording.data?.status === 'NONE'
          ? '녹화 없이 면접 기록을 확인할 수 있습니다.'
          : '녹화를 준비하고 있습니다.'}
      </p>
    );
  return (
    <video
      ref={videoRef}
      controls
      playsInline
      className="mt-3 aspect-video w-full rounded-xl bg-black"
      aria-label="선택한 면접 답변 녹화"
    />
  );
}

function ComparisonCard({ interviewId }: { interviewId: string }) {
  const cache = useQueryClient();
  const [atSec, setAtSec] = useState<number | null>(null);
  const query = useQuery({
    queryKey: ['review', interviewId],
    queryFn: () => getReview(interviewId),
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? 3000 : false),
  });
  const owner = useQuery({
    queryKey: ['interview', interviewId],
    queryFn: () => getInterview(interviewId),
  });
  const mark = useMutation({
    mutationFn: ({ id, state }: { id: string; state: Finding['state'] }) =>
      putMark(interviewId, id, { state }),
    onSettled: async () => {
      await Promise.all([
        cache.invalidateQueries({ queryKey: ['review', interviewId] }),
        cache.invalidateQueries({ queryKey: ['interviews'] }),
        cache.invalidateQueries({ queryKey: ['report', interviewId] }),
      ]);
    },
  });
  const review = query.data?.status === 'READY' ? query.data : undefined;
  return (
    <article className="border-border-base bg-surface-panel min-w-0 rounded-2xl border p-4 sm:p-5">
      <header className="border-border-base flex items-start justify-between gap-3 border-b pb-4">
        <div>
          <h2 className="text-ink text-lg font-bold">
            {review?.candidate.name || owner.data?.candidateName || '면접 확인 중'}
          </h2>
          <p className="text-ink-muted mt-1 text-xs">
            {review?.interviewedAt
              ? new Date(review.interviewedAt).toLocaleString('ko-KR')
              : '진행 일시 확인 중'}
          </p>
        </div>
        {review && (
          <Badge tone={STATUS_TONE[review.reviewStatus]}>{STATUS_LABEL[review.reviewStatus]}</Badge>
        )}
      </header>
      {query.isError ? (
        <p role="alert" className="text-danger mt-4 text-sm">
          면접 기록을 읽지 못했습니다.{' '}
          <button type="button" onClick={() => void query.refetch()} className="underline">
            다시 확인
          </button>
        </p>
      ) : !review ? (
        <p role="status" className="text-ink-muted mt-4 text-sm">
          면접 기록이 아직 준비되지 않았습니다.
        </p>
      ) : (
        <div className="mt-4 space-y-4">
          <section>
            <h3 className="text-ink text-sm font-semibold">면접 요약</h3>
            <p className="text-ink-muted mt-2 text-sm leading-relaxed">
              {review.summary?.overview ||
                (review.summaryStatus === 'FAILED'
                  ? '요약을 만들지 못했습니다. 아래 면접 기록을 확인해 주세요.'
                  : '요약이 없습니다.')}
            </p>
          </section>
          {atSec !== null && <ComparisonRecording sessionId={review.sessionId} atSec={atSec} />}
          {mark.isError && (
            <p role="alert" className="text-danger text-sm">
              선택을 저장하지 못했습니다. 현재 검토 상태를 다시 확인해 주세요.
            </p>
          )}
          <Findings
            coverage={review.coverage}
            findings={review.findings}
            findingsStatus={review.findingsStatus}
            locked={review.reviewStatus === 'CONFIRMED'}
            pendingIds={
              mark.isPending ? new Set(review.findings.map((finding) => finding.id)) : undefined
            }
            onMark={(id, state) => {
              if (!mark.isPending) mark.mutate({ id, state });
            }}
            onSeek={setAtSec}
          />
        </div>
      )}
      {(review || owner.data?.memo !== undefined) && (
        <div className="mt-4">
          <ReviewNotes interviewId={interviewId} memo={review?.memo ?? owner.data?.memo ?? ''} />
        </div>
      )}
      <div className="mt-4">
        <ReportPanel interviewId={interviewId} />
      </div>
    </article>
  );
}

export function InterviewComparison({
  ids,
  onBack,
}: {
  ids: [string, string];
  onBack: () => void;
}) {
  return (
    <section className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-ink text-lg font-semibold">선택한 두 명 비교</h2>
        <button
          type="button"
          onClick={onBack}
          className="text-brand min-h-10 rounded-lg px-3 text-sm underline"
        >
          목록으로 돌아가기
        </button>
      </div>
      <div className="grid items-start gap-4 xl:grid-cols-2">
        {ids.map((id) => (
          <ComparisonCard key={id} interviewId={id} />
        ))}
      </div>
    </section>
  );
}
