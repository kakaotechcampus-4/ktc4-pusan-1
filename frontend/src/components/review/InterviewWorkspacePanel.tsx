import type { InterviewListItem } from '../../types/interview';
import { ProcessingStatus } from './ProcessingStatus';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { getInterview } from '../../api/interview';
import { ApiError } from '../../api/client';
import ReviewTimelinePage from '../../pages/ReviewTimelinePage';
import { ReviewNotes } from './ReviewNotes';
import { ReportPanel } from './ReportPanel';
import { InvitationActions } from '../interview/InvitationActions';

type Tab = 'review' | 'memo' | 'report' | 'invitation';

export function InterviewWorkspacePanel({
  item,
  onClose,
  onPrevious,
  onNext,
}: {
  item: InterviewListItem;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
}) {
  const interviewId = item.interviewId;
  const [tab, setTab] = useState<Tab>('review');
  const owner = useQuery({
    queryKey: ['interview', interviewId],
    queryFn: () => getInterview(interviewId),
  });
  const tabs: [Tab, string][] = [
    ['review', '면접 기록'],
    ['memo', '메모'],
    ['report', '리포트'],
    ['invitation', '초대 링크'],
  ];
  return (
    <section
      aria-label="선택한 면접"
      className="border-brand/20 bg-surface-container w-[calc(100vw-3rem)] border-y lg:w-full"
    >
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <h2 className="text-ink text-base font-semibold">
          {owner.data?.candidateName || '선택한 면접'}
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={!onPrevious}
            onClick={onPrevious}
            className="text-brand min-h-10 rounded-lg px-3 text-xs disabled:opacity-40"
          >
            이전 지원자
          </button>
          <button
            type="button"
            disabled={!onNext}
            onClick={onNext}
            className="text-brand min-h-10 rounded-lg px-3 text-xs disabled:opacity-40"
          >
            다음 지원자
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-muted min-h-10 rounded-lg px-3 text-xs"
          >
            접기
          </button>
        </div>
      </header>
      <ProcessingStatus item={item} />
      <div
        role="tablist"
        aria-label="면접 작업"
        className="border-border-base flex flex-wrap gap-3 border-y px-4"
      >
        {tabs.map(([id, label]) => (
          <button
            key={id}
            id={`workspace-tab-${interviewId}-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls={`workspace-panel-${interviewId}`}
            onClick={() => setTab(id)}
            className={`min-h-11 border-b-2 px-2 text-sm ${tab === id ? 'border-brand text-brand font-semibold' : 'text-ink-muted border-transparent'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        id={`workspace-panel-${interviewId}`}
        role="tabpanel"
        aria-labelledby={`workspace-tab-${interviewId}-${tab}`}
      >
        {owner.isError ? (
          <p role="alert" className="text-danger p-4 text-sm">
            {owner.error instanceof ApiError && owner.error.status === 404
              ? '없거나 볼 수 없는 면접입니다.'
              : '면접 정보를 읽지 못했습니다.'}
            <button type="button" onClick={() => void owner.refetch()} className="ml-2 underline">
              다시 확인
            </button>
          </p>
        ) : !owner.data ? (
          <p role="status" className="text-ink-muted p-4 text-sm">
            면접 정보를 확인하고 있습니다.
          </p>
        ) : (
          <>
            {tab === 'review' && <ReviewTimelinePage interviewId={interviewId} embedded />}
            {tab === 'memo' && (
              <div className="p-4">
                {owner.data.memo === undefined ? (
                  <p className="text-warning text-sm">
                    현재 서버에서 저장된 메모를 조회할 수 없습니다. 면접 기록에서 확인해 주세요.
                  </p>
                ) : (
                  <ReviewNotes interviewId={interviewId} memo={owner.data.memo} />
                )}
              </div>
            )}
            {tab === 'report' && (
              <div className="p-4">
                <ReportPanel interviewId={interviewId} />
              </div>
            )}
            {tab === 'invitation' && (
              <div className="p-4">
                <InvitationActions interviewId={interviewId} />
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
