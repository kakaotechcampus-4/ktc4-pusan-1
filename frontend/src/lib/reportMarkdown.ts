import { fmt } from './format.ts';
import { FINDING_LABEL } from './reviewLabels.ts';
import type { ReportDocument, ReportStatement } from '../types/report';

const DISCLAIMER = 'IRYA가 면접관이 선택한 내용을 정리했습니다. 평가 점수가 아닙니다.';

/** 목록 한 줄 안에 들어가도록 줄바꿈을 공백으로 바꾼다 */
const inline = (text: string) => text.replace(/\s*\r?\n\s*/g, ' ').trim();
/** 문단 안의 줄바꿈을 Markdown 강제 줄바꿈으로 남긴다 */
const paragraph = (text: string) => text.trim().split(/\r?\n/).join('  \n');
const dateTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString('ko-KR') : null);

function statements(title: string, items: ReportStatement[]): string[] {
  if (!items.length) return [];
  return [
    `### ${title}`,
    '',
    ...items.flatMap((s) => [
      `- **${FINDING_LABEL[s.findingType]}** ${inline(s.text)}`,
      ...(s.quote ? [`  - ${s.source ?? '지원서'}: “${inline(s.quote)}”`] : []),
      ...(s.transcript
        ? [
            `  - 면접 답변${s.atSec === null ? '' : ` (${fmt(s.atSec)})`}: “${inline(s.transcript)}”`,
          ]
        : []),
    ]),
    '',
  ];
}

/**
 * 리포트를 화면과 같은 순서의 Markdown 으로 옮긴다.
 * 화면에서는 접혀 있는 면접 답변 원문도 펼쳐서 넣는다 — 받는 사람은 클릭할 수 없다.
 */
export function reportToMarkdown(report: ReportDocument): string {
  const meta = [
    `현재 설정 직무: ${report.candidate.role}`,
    `면접관: ${report.interviewer.nickname}`,
    dateTime(report.interviewedAt) && `면접 일시: ${dateTime(report.interviewedAt)}`,
    dateTime(report.generatedAt) && `리포트 생성: ${dateTime(report.generatedAt)}`,
  ].filter(Boolean);

  const lines = [
    `# ${report.candidate.name || '이름 없는 지원자'} · 면접 리포트`,
    '',
    ...meta.map((m) => `- ${m}`),
    '',
    '## 면접관 메모',
    '',
    paragraph(report.memo) || '작성된 메모가 없습니다.',
    '',
    '## 면접 요약',
    '',
    paragraph(report.overview),
    '',
    ...report.competencies.flatMap((c) => [
      `## ${c.name} (${c.required ? '필수' : '우대'})`,
      '',
      ...(c.state === 'MISSING'
        ? ['_이번 면접에서 다루지 않음_', '']
        : [
            ...statements('확인된 점', c.confirmed),
            ...statements('확인되지 않은 점', c.unconfirmed),
          ]),
      ...(c.nextQuestions.length
        ? ['### 다음에 물어볼 것', '', ...c.nextQuestions.map((q) => `- ${inline(q)}`), '']
        : []),
    ]),
    '---',
    '',
    DISCLAIMER,
    '',
  ];
  return lines.join('\n');
}

/** 운영체제가 파일 이름으로 받지 않는 글자를 뺀다 */
export function reportFileName(report: ReportDocument, ext: string): string {
  const when = report.interviewedAt ?? report.generatedAt;
  const day = when ? new Date(when).toLocaleDateString('sv-SE') : '';
  const name = (report.candidate.name || '지원자')
    .replace(/[\\/:*?"<>|\s]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return ['IRYA_리포트', name, day].filter(Boolean).join('_') + `.${ext}`;
}
