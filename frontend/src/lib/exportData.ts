import { FINDING_LABEL } from './reviewLabels.ts';
import type { InterviewListItem, ReviewResponse } from '../types/interview';
import type { ReportResponse } from '../types/report';

export interface ExportRecord {
  item: InterviewListItem;
  review: ReviewResponse;
  report: ReportResponse;
}
type Cell = string | number | null;

export function exportSheets(records: readonly ExportRecord[]): Record<string, Cell[][]> {
  const sheets: Record<string, Cell[][]> = {
    '면접 목록': [
      [
        '면접 ID',
        '지원자',
        '현재 설정 직무',
        '면접 일시',
        '길이(초)',
        '검토 상태',
        '정리 상태',
        '리포트 상태',
        '면접관 메모',
      ],
    ],
    '확인할 내용': [
      [
        '면접 ID',
        '기준 세션',
        '항목 ID',
        '종류',
        '역량',
        '내용',
        '선택 상태',
        '지원서 내용',
        '면접 답변',
        '시각(초)',
      ],
    ],
    '질문과 답변': [
      ['면접 ID', '기준 세션', '질문 ID', '시각(초)', '질문', '답변 요약', '관련 항목', '북마크'],
    ],
    리포트: [
      [
        '면접 ID',
        '기준 세션',
        '생성 시각',
        '상태',
        '항목',
        '구분',
        '내용',
        '선택 항목 ID',
        '지원서 내용',
        '면접 답변',
        '시각(초)',
      ],
    ],
  };
  const states = { PENDING: '대기', IN_REVIEW: '검토 중', CONFIRMED: '완료' };
  for (const { item, review, report } of records) {
    sheets['면접 목록'].push([
      item.interviewId,
      item.candidateName,
      item.role,
      item.interviewedAt,
      item.durationSec,
      states[review.status === 'READY' ? review.reviewStatus : item.reviewStatus],
      item.summaryStatus,
      report.status === 'NOT_CREATED' ? '미생성' : report.status,
      review.status === 'READY' ? review.memo : (item.memo ?? null),
    ]);
    if (review.status === 'READY') {
      for (const finding of review.findings)
        sheets['확인할 내용'].push([
          item.interviewId,
          review.sessionId,
          finding.id,
          FINDING_LABEL[finding.type],
          finding.competency,
          finding.rationale,
          { PROPOSED: '미선택', ADOPTED: '포함', REJECTED: '제외' }[finding.state],
          finding.quote,
          finding.transcript,
          finding.atSec,
        ]);
      for (const moment of review.moments)
        sheets['질문과 답변'].push([
          item.interviewId,
          review.sessionId,
          moment.id,
          moment.atSec,
          moment.question,
          moment.answer,
          moment.competencies.join(' · '),
          moment.bookmarked ? '예' : '아니오',
        ]);
    }
    if (report.status === 'READY' || report.status === 'FAILED') {
      const base: Cell[] = [item.interviewId, report.sessionId, report.generatedAt, report.status];
      sheets['리포트'].push([...base, '', '면접관 메모', report.memo, null, null, null, null]);
      sheets['리포트'].push([...base, '', '개요', report.overview, null, null, null, null]);
      if (report.status === 'FAILED')
        sheets['리포트'].push([
          ...base,
          '',
          '실패 사유',
          report.failureReason,
          null,
          null,
          null,
          null,
        ]);
      for (const competency of report.competencies) {
        for (const [kind, statements] of [
          ['확인된 점', competency.confirmed],
          ['확인되지 않은 점', competency.unconfirmed],
        ] as const)
          for (const statement of statements)
            sheets['리포트'].push([
              ...base,
              competency.name,
              kind,
              statement.text,
              statement.findingId,
              statement.quote,
              statement.transcript,
              statement.atSec,
            ]);
        if (competency.state === 'MISSING')
          sheets['리포트'].push([
            ...base,
            competency.name,
            '다루지 않음',
            '이번 면접에서 다루지 않음',
            null,
            null,
            null,
            null,
          ]);
        for (const question of competency.nextQuestions)
          sheets['리포트'].push([
            ...base,
            competency.name,
            '다음에 물어볼 것',
            question,
            null,
            null,
            null,
            null,
          ]);
      }
    } else
      sheets['리포트'].push([
        item.interviewId,
        null,
        null,
        report.status === 'NOT_CREATED' ? '미생성' : '처리 중',
        null,
        null,
        null,
        null,
        null,
        null,
        null,
      ]);
  }
  return sheets;
}

export async function buildExportBlob(records: readonly ExportRecord[]): Promise<Blob> {
  const { default: writeExcelFile } = await import('write-excel-file/browser');
  const sheets = Object.entries(exportSheets(records)).map(([sheet, rows]) => ({
    sheet,
    data: rows.map((row, index) =>
      row.map((value) =>
        value === null
          ? null
          : typeof value === 'number'
            ? { type: Number, value }
            : { type: String, value, fontWeight: index === 0 ? ('bold' as const) : undefined },
      ),
    ),
    columns: rows[0].map(() => ({ width: 28 })),
    stickyRowsCount: 1,
    stickyColumnsCount: 1,
  }));
  return writeExcelFile(sheets).toBlob();
}
