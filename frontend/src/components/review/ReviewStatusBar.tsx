/**
 * 검토 상태 막대 — 면접 기록 화면 아래에 붙어 따라온다 (#137 1-3, #232).
 *
 * 영상을 보다가도, 검토 항목을 내리다가도 손 닿는 곳에서 확정할 수 있게 둔다.
 * 확정할 때 아직 판단하지 않은 항목이 있으면 그 수를 옆에 적는다 — 막지는 않는다.
 */

import { useState } from 'react';
import { updateReview } from '../../api/review';
import { STATUS_LABEL } from '../../lib/interviewList';
import type { ReviewStatus, ReviewUpdateResponse } from '../../types/interview';

const STATUSES: ReviewStatus[] = ['PENDING', 'IN_REVIEW', 'CONFIRMED'];

export interface ReviewStatusBarProps {
  interviewId: string;
  embedded?: boolean;
  reviewStatus: ReviewStatus;
  reviewedAt: string | null;
  /** 아직 채택도 반려도 안 한 검토 항목 수 */
  openFindings: number;
  /** 검토 항목을 만들지 못했으면 「모두 판단했습니다」가 거짓이라 숨긴다 (#244) */
  findingsFailed: boolean;
  onSaved: (saved: Pick<ReviewUpdateResponse, 'reviewStatus' | 'reviewedAt'>) => void;
}

export function ReviewStatusBar({
  interviewId,
  embedded = false,
  reviewStatus,
  reviewedAt,
  openFindings,
  findingsFailed,
  onSaved,
}: ReviewStatusBarProps) {
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  const change = (next: ReviewStatus) => {
    if (next === reviewStatus || saving) return;
    setSaving(true);
    setFailed(false);
    updateReview(interviewId, { reviewStatus: next })
      // 메모는 메모 칸이 따로 저장한다. 여기서 받은 메모로 덮으면 입력 중인 글이 밀린다.
      .then(({ reviewStatus, reviewedAt }) => onSaved({ reviewStatus, reviewedAt }))
      .catch(() => setFailed(true))
      .finally(() => setSaving(false));
  };

  const confirmed = reviewStatus === 'CONFIRMED';

  return (
    // 좁은 화면은 아래 탭 위, 넓은 화면은 사이드바 오른쪽에 붙는다 (AppShell 의 폭과 같다).
    <div
      className={
        embedded
          ? 'border-border-base bg-surface-panel relative mt-4 border-t'
          : 'border-border-base bg-surface-panel/95 fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom))] z-20 border-t backdrop-blur-xl lg:bottom-0 lg:left-64'
      }
    >
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6 lg:px-8">
        <p aria-live="polite" className="min-w-0 flex-1 text-[14px]">
          {failed ? (
            <span className="text-danger">상태를 바꾸지 못했습니다. 다시 눌러주세요.</span>
          ) : confirmed && reviewedAt ? (
            <span className="text-accent-strong inline-flex items-center gap-1.5 font-semibold">
              <span aria-hidden className="material-symbols-outlined text-[18px]">
                check_circle
              </span>
              {new Date(reviewedAt).toLocaleString('ko-KR', {
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}{' '}
              확정
            </span>
          ) : openFindings > 0 ? (
            <span className="text-ink-muted">
              아직 판단하지 않은 검토 항목{' '}
              <span className="text-warning font-semibold">{openFindings}건</span>
            </span>
          ) : (
            !findingsFailed && (
              <span className="text-ink-muted">검토 항목을 모두 판단했습니다.</span>
            )
          )}
        </p>

        <div
          role="radiogroup"
          aria-label="검토 상태"
          className="bg-surface-bright flex gap-1 rounded-xl p-1"
        >
          {STATUSES.map((id) => {
            const on = id === reviewStatus;
            return (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={saving}
                onClick={() => change(id)}
                className={`rounded-lg px-3 py-2 text-[14px] font-semibold transition disabled:opacity-60 sm:px-4 ${
                  on
                    ? id === 'CONFIRMED'
                      ? 'bg-accent-strong shadow-card text-white'
                      : 'bg-surface-panel text-ink shadow-card'
                    : 'text-ink-muted hover:text-ink'
                }`}
              >
                {STATUS_LABEL[id]}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
