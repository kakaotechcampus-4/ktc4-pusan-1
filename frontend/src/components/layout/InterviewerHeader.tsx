import { Link } from 'react-router-dom';

export function InterviewerHeader({ demo = false }: { demo?: boolean }) {
  const candidatePath = demo ? '/demo/candidates' : '/candidates';

  return (
    <header className="border-border-base sticky top-0 z-30 border-b bg-[#15161b]/95 backdrop-blur-xl">
      <div className="mx-auto flex min-h-14 max-w-[1440px] items-center justify-between gap-5 px-4 sm:px-6 lg:px-8">
        <Link to="/" className="text-ink flex shrink-0 items-center gap-2 text-sm font-bold">
          <span className="flex h-7 w-7 items-center justify-center rounded border border-[#44474a] bg-[#202229] font-mono text-[11px]">
            I
          </span>
          <span>IRYA</span>
        </Link>

        <nav aria-label="면접관 메뉴" className="flex items-center gap-1 overflow-x-auto text-xs">
          <Link
            className="rounded px-3 py-2 text-[#c4c7c9] hover:bg-[#22242c] hover:text-white"
            to="/"
          >
            홈
          </Link>
          <Link
            aria-current="page"
            className="rounded border border-[#2e323c] bg-[#202229] px-3 py-2 font-semibold text-white"
            to={candidatePath}
          >
            지원자 검토
          </Link>
        </nav>

        {demo && (
          <span className="shrink-0 rounded border border-amber-500/40 bg-[#191a20] px-2 py-1 font-mono text-[10px] font-semibold text-[#ffe082]">
            샘플 데이터
          </span>
        )}
      </div>
    </header>
  );
}
