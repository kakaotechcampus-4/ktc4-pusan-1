import { getReview } from '../api/review';
import { getReport } from '../api/report';
import { readAccessToken } from './authToken';
import { buildExportBlob, type ExportRecord } from './exportData';
import type { InterviewListItem } from '../types/interview';

export async function candidateExport(
  items: readonly InterviewListItem[],
  progress: (done: number, total: number) => void,
): Promise<Blob> {
  const token = readAccessToken();
  const records: ExportRecord[] = new Array(items.length);
  let next = 0;
  let done = 0;
  let failed = false;
  const worker = async () => {
    while (next < items.length && !failed) {
      if (readAccessToken() !== token) throw new Error('로그인 상태가 바뀌었습니다.');
      const index = next++;
      const item = items[index];
      try {
        // 두 작업씩 처리하므로 동시에 보내는 HTTP 조회는 최대 네 개다.
        const [review, report] = await Promise.all([
          getReview(item.interviewId),
          getReport(item.interviewId),
        ]);
        records[index] = { item, review, report };
        progress(++done, items.length);
      } catch {
        failed = true;
        throw new Error(
          `${item.candidateName || item.interviewId}의 자료를 읽지 못해 내보내기를 중단했습니다.`,
        );
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, items.length) }, worker));
  if (readAccessToken() !== token) throw new Error('로그인 상태가 바뀌었습니다.');
  const blob = await buildExportBlob(records);
  if (readAccessToken() !== token) throw new Error('로그인 상태가 바뀌었습니다.');
  return blob;
}
