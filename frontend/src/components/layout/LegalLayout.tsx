/**
 * 이용약관 · 개인정보처리방침이 같이 쓰는 틀. 로그인 없이 열린다.
 *
 * 본문은 조항 단위(`<section>` + `<h2>`)로 쓰고, 모양은 여기서 한 번에 입힌다.
 */

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Logo } from '../ui/Logo';

const REPO_ISSUES_URL = 'https://github.com/kakaotechcampus-4/ktc4-pusan-1/issues';

export function LegalLayout({
  title,
  effectiveDate,
  children,
}: {
  title: string;
  effectiveDate: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-surface min-h-full">
      <header className="border-border-base bg-surface-panel border-b">
        <div className="mx-auto flex h-16 max-w-3xl items-center gap-4 px-4 sm:px-6">
          <Link to="/" aria-label="IRYA 홈">
            <Logo />
          </Link>
          <span className="flex-1" />
          <nav aria-label="정책" className="text-ink-muted flex gap-4 text-[14px]">
            <Link to="/terms" className="hover:text-ink">
              이용약관
            </Link>
            <Link to="/privacy" className="hover:text-ink">
              개인정보처리방침
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <h1 className="text-ink text-[30px] font-bold tracking-tight">{title}</h1>
        <p className="text-ink-dim mt-2 text-[14px]">시행일 {effectiveDate}</p>
        <p className="bg-brand-tint text-brand-strong mt-6 rounded-xl px-4 py-3 text-[14px] leading-relaxed">
          IRYA 는 카카오테크캠퍼스 4기 부산대 1팀의 학생 프로젝트입니다. 이 문서는 프로젝트 운영을
          위해 작성되었으며, 상용 서비스로 전환할 때 법률 검토를 거쳐 다시 고지합니다.
        </p>
        <article className="text-ink-muted [&_h2]:text-ink [&_td]:border-border-base text-[15px] leading-relaxed [&_h2]:text-[18px] [&_h2]:font-semibold [&_li]:mt-1 [&_ol]:mt-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mt-2 [&_section]:mt-10 [&_table]:mt-3 [&_table]:w-full [&_table]:text-[14px] [&_td]:border-t [&_td]:py-2.5 [&_td]:pr-3 [&_td]:align-top [&_th]:pb-2 [&_th]:text-left [&_th]:font-semibold [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5">
          {children}
        </article>
        <p className="text-ink-dim border-border-base mt-14 border-t pt-6 text-[14px]">
          문의: 부산대 1팀 ·{' '}
          <a href={REPO_ISSUES_URL} target="_blank" rel="noreferrer" className="underline">
            GitHub 이슈
          </a>
        </p>
      </main>
    </div>
  );
}
