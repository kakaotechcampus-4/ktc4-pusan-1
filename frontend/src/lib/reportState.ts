import type { Review } from '../types/interview';
import type { ReportDocument } from '../types/report';

export function reportBlockReason(review: Review | undefined): string | null {
  if (!review || review.reviewStatus !== 'CONFIRMED') return '검토를 완료해 주세요.';
  if (!review.findings.some((finding) => finding.state === 'ADOPTED'))
    return '리포트에 포함할 내용이 없습니다.';
  return null;
}

export function reportIsStale(report: ReportDocument, review: Review | undefined): boolean {
  if (!review || report.status !== 'READY') return false;
  return (
    review.reviewStatus !== 'CONFIRMED' ||
    report.memo !== review.memo ||
    report.sessionId !== review.sessionId ||
    Boolean(
      review.reviewedAt &&
      report.generatedAt &&
      Date.parse(review.reviewedAt) > Date.parse(report.generatedAt),
    )
  );
}
