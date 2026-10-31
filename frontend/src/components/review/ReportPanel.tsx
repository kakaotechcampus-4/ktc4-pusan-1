import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { createReport, getReport } from '../../api/report';
import { getReview } from '../../api/review';
import { reportBlockReason, reportIsStale } from '../../lib/reportState';
import { buttonClass } from '../ui/buttonClass';
import { ReportContent } from './ReportContent';
import { flushMemosForRead } from '../../hooks/useMemoAutosave';

export function ReportPanel({
  interviewId,
  compact = false,
}: {
  interviewId: string;
  compact?: boolean;
}) {
  const client = useQueryClient();
  const report = useQuery({
    queryKey: ['report', interviewId],
    queryFn: () => getReport(interviewId),
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? 3000 : false),
  });
  const reviewQuery = useQuery({
    queryKey: ['review', interviewId],
    queryFn: () => getReview(interviewId),
    refetchInterval: (q) => (q.state.data?.status === 'PROCESSING' ? 3000 : false),
  });
  const review = reviewQuery.data?.status === 'READY' ? reviewQuery.data : undefined;
  const reason = reportBlockReason(review);
  const create = useMutation({
    mutationFn: async () => {
      await flushMemosForRead([interviewId]);
      return createReport(interviewId);
    },
    onSuccess: async (processing) => {
      client.setQueryData(['report', interviewId], processing);
      await client.invalidateQueries({ queryKey: ['interviews'] });
    },
    onError: async () => {
      await Promise.all([report.refetch(), reviewQuery.refetch()]);
    },
  });
  const data = report.data;
  const error =
    create.error instanceof ApiError
      ? ({
          REVIEW_NOT_CONFIRMED: '다른 창에서 검토 상태가 바뀌었습니다. 다시 확인해 주세요.',
          NO_ADOPTED_FINDING: '리포트에 포함할 내용이 없습니다.',
          REPORT_IN_PROGRESS: '이미 리포트를 만들고 있습니다.',
        }[create.error.code] ?? '생성을 요청하지 못했습니다. 현재 상태를 다시 확인해 주세요.')
      : create.error
        ? create.error.message
        : null;
  if (report.isError)
    return (
      <div role="alert" className="text-danger text-sm">
        <p>
          {report.error instanceof ApiError && report.error.status === 404
            ? '없거나 볼 수 없는 면접입니다.'
            : '리포트를 불러오지 못했습니다.'}
        </p>
        <button
          type="button"
          onClick={() => void report.refetch()}
          className="text-brand mt-2 underline"
        >
          다시 확인
        </button>
      </div>
    );
  if (!data)
    return (
      <p role="status" className="text-ink-muted text-sm">
        리포트를 확인하고 있습니다.
      </p>
    );
  if (data.status === 'PROCESSING')
    return (
      <div role="status" className="bg-surface-bright text-ink-muted rounded-xl p-4 text-sm">
        <p className="text-ink font-semibold">리포트를 만들고 있습니다.</p>
        <p className="mt-2">이 화면을 나가도 작업은 계속됩니다. 완료되면 자동으로 표시합니다.</p>
      </div>
    );
  if (data.status === 'READY') {
    if (reportIsStale(data, review))
      return (
        <p role="status" className="text-warning text-sm">
          현재 검토와 리포트의 기준이 다릅니다. 면접 기록을 다시 확인해 주세요.
        </p>
      );
    return compact ? (
      <Link to={`/report/${interviewId}`} className={buttonClass('secondary')}>
        리포트 보기
      </Link>
    ) : (
      <ReportContent report={data} />
    );
  }
  if (data.status === 'FAILED')
    return (
      <div role="status" className="text-warning text-sm">
        <p>
          {data.failureReason === 'NO_EVIDENCE'
            ? '선택한 내용으로 리포트를 구성하지 못했습니다.'
            : '리포트를 만들지 못했습니다.'}
        </p>
        <button
          type="button"
          onClick={() => void report.refetch()}
          className="text-brand mt-2 underline"
        >
          다시 확인
        </button>
      </div>
    );
  return (
    <div>
      <button
        type="button"
        disabled={Boolean(reason) || create.isPending}
        onClick={() => create.mutate()}
        className={buttonClass('primary')}
        title={reason ?? undefined}
      >
        {create.isPending
          ? '생성 요청 중'
          : `리포트 만들기 (포함 ${review?.findings.filter((f) => f.state === 'ADOPTED').length ?? 0}개)`}
      </button>
      {reason && <p className="text-ink-muted mt-2 text-xs">{reason}</p>}
      {(error || reviewQuery.isError) && (
        <p role="alert" className="text-danger mt-2 text-sm">
          {error ?? '검토 상태를 확인하지 못했습니다.'}
        </p>
      )}
    </div>
  );
}
