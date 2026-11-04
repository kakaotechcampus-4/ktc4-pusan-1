/**
 * 면접관 화면의 틀 (#232).
 *
 * 넓은 화면은 왼쪽 사이드바, 좁은 화면은 위 막대 + 아래 탭이다. 면접관이 하는 일은
 * 「면접 만들기 → 지원자 검토」 둘이라 그 둘을 가장 눈에 띄게 두고, 링크로 바로 여는
 * 기능(면접 입장 · 요약 · 기록)과 계정은 한 단계 안쪽(사이드바 아래 · 더보기 시트)에 둔다.
 *
 * 면접 진행 화면은 화면 전체를 쓰므로 이 틀 밖에 있다 (`App.tsx` 의 `InterviewEntry`).
 */

import { useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { getMe, type User } from '../../api/auth';
import { useAccessToken } from '../../hooks/useAccessToken';
import { useLogout } from '../../hooks/useLogout';
import { buttonClass } from '../ui/buttonClass';
import { Logo } from '../ui/Logo';
import { Sheet } from '../ui/Sheet';
import { InterviewNavigationDialog } from './InterviewNavigationDialog';

type Shortcut = 'room' | 'summary' | 'review';

const NAV = [
  { to: '/', label: '홈', icon: 'home', end: true },
  { to: '/candidates', label: '지원자', icon: 'group', end: false },
  { to: '/settings/context', label: '기업 설정', icon: 'apartment', end: false },
];

const SHORTCUTS: { id: Shortcut; label: string; icon: string }[] = [
  { id: 'room', label: '면접 입장', icon: 'login' },
  { id: 'summary', label: '면접 요약', icon: 'summarize' },
  { id: 'review', label: '면접 기록', icon: 'history' },
];

export function AppShell({ children }: { children: ReactNode }) {
  const token = useAccessToken();
  // RequireAuth 가 이미 불러 둔 값을 그대로 쓴다 — 같은 키라 요청이 더 나가지 않는다.
  const { data: me } = useQuery({ queryKey: ['me', token], queryFn: getMe });
  const logout = useLogout();
  const [shortcut, setShortcut] = useState<Shortcut | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);

  const openShortcut = (id: Shortcut) => {
    setMoreOpen(false);
    setShortcut(id);
  };

  return (
    <div className="bg-surface min-h-full">
      {/* ── 넓은 화면: 사이드바 ── */}
      <aside className="border-border-base bg-surface-panel fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r px-4 py-5 lg:flex">
        <Link to="/" aria-label="IRYA 홈" className="px-2">
          <Logo />
        </Link>

        <Link to="/interviews/new" className={`${buttonClass('primary')} mt-7 w-full`}>
          <span aria-hidden className="material-symbols-outlined text-[20px]">
            add
          </span>
          새 면접
        </Link>

        <nav aria-label="면접관 메뉴" className="mt-5 flex flex-col gap-1">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={sideLinkClass}>
              <span aria-hidden className="material-symbols-outlined text-[21px]">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <p className="text-ink-dim mt-8 px-3 text-[12px] font-semibold">링크로 열기</p>
        <div className="mt-1.5 flex flex-col gap-0.5">
          {SHORTCUTS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setShortcut(s.id)}
              className="text-ink-muted hover:bg-surface-bright hover:text-ink flex items-center gap-3 rounded-lg px-3 py-2 text-[14px] transition-colors"
            >
              <span aria-hidden className="material-symbols-outlined text-[19px]">
                {s.icon}
              </span>
              {s.label}
            </button>
          ))}
        </div>

        <span className="flex-1" />

        <div className="border-border-base border-t pt-4">
          <Account me={me} />
          <button
            type="button"
            onClick={logout}
            className="text-ink-muted hover:bg-surface-bright hover:text-ink mt-2 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[14px] transition-colors"
          >
            <span aria-hidden className="material-symbols-outlined text-[19px]">
              logout
            </span>
            로그아웃
          </button>
          <PolicyLinks />
        </div>
      </aside>

      {/* ── 좁은 화면: 위 막대 ── */}
      <header className="border-border-base bg-surface-panel/90 sticky top-0 z-30 flex h-14 items-center border-b px-4 backdrop-blur-xl lg:hidden">
        <Link to="/" aria-label="IRYA 홈">
          <Logo size="sm" />
        </Link>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          aria-label="계정 메뉴"
          className="rounded-full"
        >
          <Avatar me={me} />
        </button>
      </header>

      <main className="pb-[calc(4.5rem+env(safe-area-inset-bottom))] lg:pb-0 lg:pl-64">
        {children}
      </main>

      {/* ── 좁은 화면: 아래 탭. 가운데가 가장 자주 하는 일(새 면접)이다 ── */}
      <nav
        aria-label="면접관 메뉴"
        className="border-border-base bg-surface-panel/95 fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      >
        <TabLink {...NAV[0]} />
        <TabLink {...NAV[1]} />
        <Link
          to="/interviews/new"
          aria-label="새 면접"
          className="flex items-center justify-center"
        >
          <span className="bg-brand shadow-pop flex h-11 w-11 items-center justify-center rounded-2xl text-white">
            <span aria-hidden className="material-symbols-outlined text-[24px]">
              add
            </span>
          </span>
        </Link>
        <TabLink {...NAV[2]} label="설정" />
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          className="text-ink-dim flex h-16 flex-col items-center justify-center gap-0.5 text-[11px] font-medium"
        >
          <span aria-hidden className="material-symbols-outlined text-[23px]">
            more_horiz
          </span>
          더보기
        </button>
      </nav>

      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} title="메뉴" side="bottom">
        <Account me={me} />
        <p className="text-ink-dim mt-6 text-[12px] font-semibold">링크로 열기</p>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {SHORTCUTS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => openShortcut(s.id)}
              className="border-border-base text-ink flex flex-col items-center gap-1.5 rounded-xl border py-4 text-[13px] font-medium"
            >
              <span aria-hidden className="material-symbols-outlined text-brand text-[22px]">
                {s.icon}
              </span>
              {s.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={logout}
          className={`${buttonClass('secondary')} mt-6 w-full`}
        >
          로그아웃
        </button>
        <PolicyLinks />
      </Sheet>

      {shortcut && (
        <InterviewNavigationDialog
          key={shortcut}
          mode={shortcut}
          onClose={() => setShortcut(null)}
        />
      )}
    </div>
  );
}

const sideLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] font-medium transition-colors ${
    isActive
      ? 'bg-brand-tint text-brand-strong'
      : 'text-ink-muted hover:bg-surface-bright hover:text-ink'
  }`;

function TabLink({
  to,
  label,
  icon,
  end,
}: {
  to: string;
  label: string;
  icon: string;
  end: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex h-16 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${
          isActive ? 'text-brand' : 'text-ink-dim'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden
            className="material-symbols-outlined text-[23px]"
            style={isActive ? { fontVariationSettings: "'FILL' 1" } : undefined}
          >
            {icon}
          </span>
          {label}
        </>
      )}
    </NavLink>
  );
}

function Avatar({ me }: { me: User | undefined }) {
  return me?.profileImageUrl ? (
    <img src={me.profileImageUrl} alt="" className="h-8 w-8 rounded-full object-cover" />
  ) : (
    <span
      aria-hidden
      className="bg-brand-tint text-brand flex h-8 w-8 items-center justify-center rounded-full"
    >
      <span className="material-symbols-outlined text-[18px]">person</span>
    </span>
  );
}

function Account({ me }: { me: User | undefined }) {
  return (
    <div className="flex items-center gap-3 px-3">
      <Avatar me={me} />
      <div className="min-w-0">
        <p className="text-ink truncate text-[14px] font-semibold">{me?.nickname ?? '면접관'}</p>
        <p className="text-ink-dim text-[12px]">카카오 계정</p>
      </div>
    </div>
  );
}

function PolicyLinks() {
  return (
    <p className="text-ink-dim mt-4 flex gap-3 px-3 text-[12px]">
      <Link to="/terms" className="hover:text-ink">
        이용약관
      </Link>
      <Link to="/privacy" className="hover:text-ink">
        개인정보처리방침
      </Link>
    </p>
  );
}
