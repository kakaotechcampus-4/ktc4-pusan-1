import { useEffect } from 'react';
import { saveDownload } from '../../lib/candidateManagement';
import { reportFileName, reportToMarkdown } from '../../lib/reportMarkdown';
import type { ReportDocument } from '../../types/report';
import { buttonClass } from '../ui/buttonClass';

/**
 * 리포트를 Markdown 파일과 PDF 로 내보낸다.
 *
 * PDF 는 브라우저 인쇄의 「PDF로 저장」을 쓴다. 글자가 그대로 남아 검색·복사가 되고
 * 한글 글꼴을 따로 싣지 않아도 된다. 인쇄 모양은 index.css 의 @media print 가 맡는다.
 */
export function ReportExportActions({ report }: { report: ReportDocument }) {
  // 접힌 면접 답변은 종이에서 펼 수 없다. Ctrl+P 로 인쇄해도 펼쳐 찍고 끝나면 되돌린다.
  useEffect(() => {
    let opened: HTMLDetailsElement[] = [];
    const expand = () => {
      opened = [
        ...document.querySelectorAll<HTMLDetailsElement>('[data-report] details:not([open])'),
      ];
      opened.forEach((d) => (d.open = true));
    };
    const restore = () => {
      opened.forEach((d) => (d.open = false));
      opened = [];
    };
    window.addEventListener('beforeprint', expand);
    window.addEventListener('afterprint', restore);
    return () => {
      window.removeEventListener('beforeprint', expand);
      window.removeEventListener('afterprint', restore);
    };
  }, []);

  return (
    <div className="mb-4 flex flex-wrap justify-end gap-2 print:hidden">
      <button
        type="button"
        className={buttonClass('secondary')}
        onClick={() =>
          saveDownload(
            new Blob([reportToMarkdown(report)], { type: 'text/markdown;charset=utf-8' }),
            reportFileName(report, 'md'),
          )
        }
      >
        <span aria-hidden className="material-symbols-outlined text-[18px]">
          download
        </span>
        Markdown 받기
      </button>
      <button type="button" className={buttonClass('secondary')} onClick={() => window.print()}>
        <span aria-hidden className="material-symbols-outlined text-[18px]">
          picture_as_pdf
        </span>
        PDF로 저장
      </button>
    </div>
  );
}
