import type { Review } from '../types/interview';
import type { ReportDocument } from '../types/report';

export function reportBlockReason(review: Review | undefined): string | null {
  if (review?.findingsStatus === 'FAILED')
    return '확인할 내용 분석에 실패했습니다. 면접 기록을 확인해 주세요.';
  if (!review || review.reviewStatus !== 'CONFIRMED') return '검토를 완료해 주세요.';
  if (!review.findings.some((finding) => finding.state === 'ADOPTED'))
    return '리포트에 포함할 내용이 없습니다.';
  return null;
}

/** stale 배너 문구. 사유마다 실제로 눌러야 하는 것이 다르다 (#293). */
export function reportStaleNotice(
  report: ReportDocument,
  review: Review | undefined,
): string | null {
  if (!reportIsStale(report, review)) return null;
  // 미확정이면 재생성 버튼이 잠겨 있다 — 확정이 먼저다.
  if (!review || review.reviewStatus !== 'CONFIRMED')
    return '현재 검토와 리포트의 기준이 다릅니다. 검토를 확정한 뒤 다시 만들어 주세요.';
  if (report.sessionId !== review.sessionId)
    return '리포트를 만든 뒤 기준 세션이 바뀌었습니다. 리포트를 다시 만들어 주세요.';
  return '검토 내용이 리포트보다 최신입니다. 리포트를 다시 만들어 주세요.';
}

export function reportIsStale(report: ReportDocument, review: Review | undefined): boolean {
  if (!review || report.status !== 'READY') return false;
  return (
    review.reviewStatus !== 'CONFIRMED' ||
    report.sessionId !== review.sessionId ||
    Boolean(
      review.reviewedAt &&
      report.generatedAt &&
      Date.parse(review.reviewedAt) > Date.parse(report.generatedAt),
    )
  );
}
