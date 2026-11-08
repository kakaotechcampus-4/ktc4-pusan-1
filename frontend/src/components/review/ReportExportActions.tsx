import { saveDownload } from '../../lib/candidateManagement';
import { reportFileName, reportToMarkdown } from '../../lib/reportMarkdown';
import type { ReportDocument } from '../../types/report';
import { buttonClass } from '../ui/buttonClass';

/** 리포트를 Markdown 파일로 내보낸다. 받는 사람이 문서 도구에 그대로 붙여 쓸 수 있다. */
export function ReportExportActions({ report }: { report: ReportDocument }) {
  return (
    <div className="mb-4 flex flex-wrap justify-end gap-2">
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
    </div>
  );
}
