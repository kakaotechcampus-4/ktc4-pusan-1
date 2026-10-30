import assert from 'node:assert/strict';
import { test } from 'node:test';
import { unzipSync, strFromU8 } from 'fflate';
import { exportSheets, buildExportBlob } from '../src/lib/exportData.ts';

const item = {
  interviewId: 'int_1',
  candidateName: '김지원',
  role: '백엔드',
  interviewedAt: null,
  durationSec: null,
  reviewStatus: 'CONFIRMED',
  summaryStatus: 'READY',
  memo: '한글\n메모',
};
const report = {
  status: 'READY',
  sessionId: 'ses_1',
  generatedAt: '2026-10-30T10:00:00Z',
  memo: '메모',
  overview: '개요',
  competencies: [
    {
      name: '정합성',
      state: 'MISSING',
      confirmed: [],
      unconfirmed: [],
      nextQuestions: ['멱등성 검증 방법은?'],
    },
  ],
};
test('빈 기록과 미생성 리포트도 상태를 남기고 MISSING 후속 질문을 내보낸다', () => {
  const sheets = exportSheets([{ item, review: { status: 'PROCESSING' }, report }]);
  assert.equal(sheets['면접 목록'][1][8], '한글\n메모');
  assert.ok(sheets['리포트'].some((row) => row[6] === '멱등성 검증 방법은?'));
  assert.ok(sheets['리포트'].some((row) => row[5] === '다루지 않음'));
  assert.equal(sheets['확인할 내용'].length, 1);
});
test('XLSX에서 한글·줄바꿈·수식처럼 보이는 메모가 문자열로 보존된다', async () => {
  const blob = await buildExportBlob([
    {
      item: { ...item, memo: '=SUM(A1)' },
      review: { status: 'PROCESSING' },
      report: { status: 'NOT_CREATED' },
    },
  ]);
  const files = unzipSync(new Uint8Array(await blob.arrayBuffer()));
  assert.equal(
    Object.keys(files).filter((name) => /^xl\/worksheets\/sheet\d+\.xml$/.test(name)).length,
    4,
  );
  const xml = Object.values(files)
    .map((bytes) => strFromU8(bytes))
    .join('');
  assert.ok(xml.includes('=SUM(A1)'));
  assert.ok(xml.includes('김지원'));
  assert.equal(/<f(?:\s|>)/.test(xml), false);
});
