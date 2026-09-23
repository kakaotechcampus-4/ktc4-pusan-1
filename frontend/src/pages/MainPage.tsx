/**
 * 메인 — 로그인 후 첫 화면.
 *
 * 면접을 만들러 가는 입구다. 기업 컨텍스트가 비어 있으면 면접을 만들어도 AI 가 근거로 쓸
 * 자료가 없으므로, 설정 화면으로 먼저 보낸다.
 *
 * ⚠️ 조직 컨텍스트 조회 API 가 없어 contextId 를 상수로 둔다. 목으로 동작한다.
 */

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getContext } from '../api/context';

/** ⚠️ 조직당 컨텍스트 하나. 실제 API 가 생기면 세션에서 가져온다. */
const CONTEXT_ID = 'ctx_demo';

export default function MainPage() {
  const { data: context, isLoading } = useQuery({
    queryKey: ['context', CONTEXT_ID],
    queryFn: () => getContext(CONTEXT_ID),
  });

  // 읽기가 끝난 문서가 하나도 없으면 아직 면접을 만들 준비가 안 된 것으로 본다.
  const ready = Boolean(context?.docs.some((d) => d.status === 'ready'));

  return (
    <div className="bg-surface min-h-full px-6 py-10 md:px-10">
      <div className="mx-auto w-full max-w-4xl">
        <header className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <div>
            <p className="text-ink-dim text-[13px]">면접 관리</p>
            <h1 className="text-ink mt-1 text-2xl font-bold tracking-tight">대시보드</h1>
          </div>
          <span className="flex-1" />
          <Link
            to="/settings/context"
            className="border-border-base bg-surface-panel text-ink hover:bg-surface-bright inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-[14px] font-medium transition"
          >
            <span aria-hidden className="material-symbols-outlined text-[18px]">
              settings
            </span>
            기업 컨텍스트 설정
          </Link>
        </header>

        <section className="border-border-base bg-surface-panel mt-8 rounded-2xl border p-6 md:p-8">
          <h2 className="text-ink text-lg font-semibold">새 면접 시작</h2>
          <p className="text-ink-muted mt-2 text-[14px] leading-relaxed">
            지원자 정보와 이력서를 넣으면 면접 링크를 만들어 드립니다. 질문과 요약은 설정해 둔 기업
            컨텍스트를 근거로 만들어집니다.
          </p>

          {/* 컨텍스트는 선택이다. 문서가 없어도 면접을 만들 수 있게 두고, 권하기만 한다. */}
          <div className="mt-6 flex flex-wrap items-center gap-2.5">
            <Link
              to="/interviews/new"
              className="bg-brand inline-flex items-center gap-2 rounded-xl px-5 py-3 text-[15px] font-medium text-white transition hover:bg-blue-700"
            >
              <span aria-hidden className="material-symbols-outlined text-[20px]">
                add
              </span>
              면접 만들기
            </Link>

            {!ready && !isLoading && (
              <Link
                to="/settings/context"
                className="border-border-base text-ink hover:bg-surface-bright inline-flex items-center gap-2 rounded-xl border px-4 py-3 text-[15px] font-medium transition"
              >
                기업 컨텍스트 설정
              </Link>
            )}
          </div>

          {!ready && !isLoading && (
            <p className="text-ink-dim mt-3 text-[13px] leading-relaxed">
              기업 컨텍스트가 비어 있어도 면접은 만들 수 있습니다. 직무 기술서나 회사 문서를 올리면
              AI 가 그 내용을 근거로 질문과 요약을 만듭니다.
            </p>
          )}
        </section>

        <section className="border-border-base bg-surface-panel mt-4 rounded-2xl border p-6">
          <h2 className="text-ink text-[15px] font-semibold">기업 컨텍스트</h2>

          {isLoading && <p className="text-ink-dim mt-3 text-[14px]">불러오는 중…</p>}

          {context && (
            <>
              <p className="text-ink-muted mt-3 text-[14px]">
                {context.company} · {context.role}
              </p>
              <p className="text-ink-dim mt-1.5 font-mono text-[13px]">
                문서 {context.docs.length}개{!ready && ' · 읽기가 끝난 문서가 없습니다'}
              </p>
              {!ready && (
                <p className="text-ink-dim mt-3 text-[13px]">
                  문서 없이 면접을 만들면 AI 가 참고할 자료 없이 질문을 만듭니다.
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
