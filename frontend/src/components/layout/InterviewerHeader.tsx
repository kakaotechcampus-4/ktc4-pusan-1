import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { InterviewNavigationDialog } from './InterviewNavigationDialog';

// 화면마다 이름과 목적지를 바꾸면 같은 메뉴가 다른 일을 하게 된다.
// 업무 목록과 샘플 화면을 구분하고, ID가 필요한 화면은 기존 링크로 열게 한다.
const MENU = [
  { to: '/', label: '홈' },
  { to: '/candidates', label: '지원자 검토' },
  { to: '/settings/context', label: '기업 설정' },
  { to: '/interviews/new', label: '면접 만들기' },
  { to: '/demo/candidates', label: '샘플 검토' },
];

export function InterviewerHeader({ demo = false }: { demo?: boolean }) {
  const { pathname } = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const items = MENU;
  const headerRef = useRef<HTMLElement>(null);
  const [destination, setDestination] = useState<'room' | 'summary' | 'review' | null>(null);
  const candidateId = /^\/demo\/candidates\/([^/]+)/.exec(pathname)?.[1] ?? 'candidate-kim';
  const samplePages = [
    { to: `/demo/candidates/${candidateId}`, label: '샘플 상세' },
    { to: `/demo/candidates/${candidateId}/memo`, label: '샘플 메모' },
    { to: '/mock/interview', label: '면접 미리보기' },
  ];
  useEffect(() => {
    // 상단 목록 높이가 화면 폭에 따라 달라도 하위 목차가 헤더와 겹치지 않는다.
    const node = headerRef.current;
    if (!node) return;
    const update = () =>
      document.documentElement.style.setProperty(
        '--interviewer-header-height',
        `${node.getBoundingClientRect().height}px`,
      );
    const observer = new ResizeObserver(update);
    observer.observe(node);
    update();
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    // 좁은 화면에서도 선택된 메뉴가 가려지지 않게 한다. 세로 위치는 그대로 둔다.
    const nav = navRef.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!nav || !active) return;
    const menuBox = nav.getBoundingClientRect();
    const activeBox = active.getBoundingClientRect();
    if (activeBox.left < menuBox.left) nav.scrollLeft -= menuBox.left - activeBox.left;
    else if (activeBox.right > menuBox.right) nav.scrollLeft += activeBox.right - menuBox.right;
  }, [pathname]);

  return (
    <header
      ref={headerRef}
      className="border-border-base sticky top-0 z-30 border-b bg-[#15161b]/95 backdrop-blur-xl"
    >
      <div className="mx-auto grid h-24 max-w-[1440px] grid-cols-[auto_1fr] grid-rows-2 items-center gap-x-4 px-4 sm:h-14 sm:grid-cols-[auto_minmax(0,1fr)_6rem] sm:grid-rows-1 sm:gap-5 sm:px-6 lg:px-8">
        <Link to="/" className="text-ink flex shrink-0 items-center gap-2 text-sm font-bold">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-[#44474a] bg-[#202229] font-mono text-[11px]">
            I
          </span>
          <span>IRYA</span>
        </Link>

        <nav
          ref={navRef}
          aria-label="면접관 메뉴"
          className="col-span-2 row-start-2 min-w-0 [scrollbar-width:none] overflow-x-auto sm:col-span-1 sm:col-start-2 sm:row-start-1 [&::-webkit-scrollbar]:hidden"
        >
          <div className="grid auto-cols-fr grid-flow-col items-center gap-1 sm:flex sm:w-max sm:min-w-full sm:justify-center">
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/' || item.to === '/demo/candidates'}
                className={({ isActive }) =>
                  `inline-flex h-11 min-w-0 items-center justify-center rounded-lg border px-1 text-center text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-[#7a97ff] focus-visible:outline-none sm:h-9 sm:shrink-0 sm:px-3 sm:whitespace-nowrap ${
                    isActive
                      ? 'border-[#3f485c] bg-[#252c3b] text-white'
                      : 'border-transparent text-[#b1b9c8] hover:border-[#2e323c] hover:bg-[#202229] hover:text-white'
                  }`
                }
              >
                <span className="min-w-0 leading-4 break-keep">{item.label}</span>
              </NavLink>
            ))}
          </div>
        </nav>

        {/* 배지 자리는 항상 유지해 샘플 화면에서도 메뉴가 옆으로 밀리지 않는다. */}
        <div className="col-start-2 row-start-1 flex w-24 justify-end justify-self-end sm:col-start-3">
          {demo && (
            <span className="rounded border border-amber-500/40 bg-[#191a20] px-2 py-1 font-mono text-[10px] font-semibold whitespace-nowrap text-[#ffe082]">
              샘플 데이터
            </span>
          )}
        </div>
      </div>
      <nav
        aria-label="전체 화면"
        className="border-border-base mx-auto grid max-w-[1440px] grid-cols-3 gap-1 border-t px-4 py-2 text-xs sm:grid-cols-6 sm:px-6 lg:px-8"
      >
        {samplePages.map((item) => (
          <NavLink
            key={item.label}
            to={item.to}
            end
            className={({ isActive }) =>
              `flex min-h-10 items-center justify-center rounded-lg px-2 text-center ${isActive ? 'bg-[#252c3b] text-white' : 'text-[#b1b9c8] hover:bg-[#202229] hover:text-white'}`
            }
          >
            {item.label}
          </NavLink>
        ))}
        <button
          type="button"
          onClick={() => setDestination('room')}
          className="min-h-10 rounded-lg px-2 text-[#b1b9c8] hover:bg-[#202229] hover:text-white"
        >
          면접 입장
        </button>
        <button
          type="button"
          onClick={() => setDestination('summary')}
          className="min-h-10 rounded-lg px-2 text-[#b1b9c8] hover:bg-[#202229] hover:text-white"
        >
          면접 요약
        </button>
        <button
          type="button"
          onClick={() => setDestination('review')}
          className="min-h-10 rounded-lg px-2 text-[#b1b9c8] hover:bg-[#202229] hover:text-white"
        >
          면접 기록
        </button>
      </nav>
      {destination && (
        <InterviewNavigationDialog
          key={destination}
          mode={destination}
          onClose={() => setDestination(null)}
        />
      )}
    </header>
  );
}
