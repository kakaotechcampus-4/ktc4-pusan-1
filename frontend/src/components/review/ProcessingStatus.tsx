import type { InterviewListItem } from '../../types/interview';

export function ProcessingStatus({ item }: { item: InterviewListItem }) {
  const summary =
    item.summaryStatus === 'PROCESSING'
      ? '정리 중'
      : item.summaryStatus === 'READY'
        ? '완료'
        : item.summaryStatus === 'FAILED'
          ? '실패'
          : '시작 전';
  const findings =
    item.findingsStatus === 'FAILED'
      ? '실패'
      : item.findingsStatus === 'EMPTY'
        ? '항목 없음'
        : item.findingsStatus === 'COMPLETED'
          ? '완료'
          : item.summaryStatus === 'PROCESSING'
            ? '정리 중'
            : '미확인';
  const recording =
    item.recordingStatus === 'PROCESSING'
      ? '준비 중'
      : item.recordingStatus === 'READY'
        ? '준비됨'
        : item.recordingStatus === 'FAILED'
          ? '실패'
          : item.recordingStatus === null
            ? '없음'
            : '미확인';
  const report =
    item.reportStatus === 'PROCESSING'
      ? '생성 중'
      : item.reportStatus === 'READY'
        ? '완료'
        : item.reportStatus === 'FAILED'
          ? '실패'
          : item.reportStatus === null
            ? '미생성'
            : '미확인';
  return (
    <div
      aria-label="면접 자료 상태"
      className="border-border-base flex flex-wrap gap-x-5 gap-y-2 border-t px-4 py-3 text-xs"
      role="status"
    >
      {[
        ['요약', summary],
        ['확인할 내용', findings],
        ['녹화', recording],
        ['리포트', report],
      ].map(([name, state]) => (
        <span
          key={name}
          className={
            state === '실패'
              ? 'text-danger'
              : state.endsWith('중')
                ? 'text-brand'
                : 'text-ink-muted'
          }
        >
          {name} · {state}
        </span>
      ))}
    </div>
  );
}
