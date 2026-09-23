import { lazy, Suspense } from 'react';
import { Link, Route, Routes, useLocation } from 'react-router-dom';
import App from './App';
import { USE_MOCK_API } from './mocks/mockApi';

const CandidateListPage = lazy(() => import('./pages/CandidateListPage'));
const CandidateDetailPage = lazy(() => import('./pages/CandidateDetailPage'));
const CandidateMemoPage = lazy(() => import('./pages/CandidateMemoPage'));

export default function ReviewEntry() {
  const { pathname } = useLocation();

  if (pathname !== '/candidates' && !pathname.startsWith('/demo/candidates')) {
    return (
      <>
        {pathname === '/' && (
          <nav
            aria-label="화면 바로가기"
            className="flex flex-wrap items-center justify-center gap-2 border-b border-[#272a33] bg-[#15161b] px-4 py-3 text-xs text-[#eaecef]"
          >
            <span className="mr-2 text-[#9498a4]">화면 바로가기</span>
            <Link
              to="/candidates"
              className="rounded border border-[#2e323c] px-3 py-2 hover:bg-[#22242c]"
            >
              지원자 목록
            </Link>
            <Link
              to="/demo/candidates"
              className="rounded border border-amber-500/40 bg-[#191a20] px-3 py-2 text-[#ffe082] hover:bg-[#22242c]"
            >
              샘플 검토 화면
            </Link>
            {USE_MOCK_API && (
              <>
                <Link
                  to="/interview/ses_demo?role=interviewer"
                  className="rounded border border-[#2e323c] px-3 py-2 hover:bg-[#22242c]"
                >
                  면접 입장·기기 점검
                </Link>
                <Link
                  to="/review/int_demo"
                  className="rounded border border-[#2e323c] px-3 py-2 hover:bg-[#22242c]"
                >
                  면접 기록 예시
                </Link>
              </>
            )}
          </nav>
        )}
        <App />
      </>
    );
  }

  return (
    <Suspense fallback={<div className="min-h-screen bg-[#121316]" />}>
      <Routes>
        <Route path="/candidates" element={<CandidateListPage />} />
        <Route path="/demo/candidates" element={<CandidateListPage demo />} />
        <Route path="/demo/candidates/:candidateId" element={<CandidateDetailPage />} />
        <Route path="/demo/candidates/:candidateId/memo" element={<CandidateMemoPage />} />
      </Routes>
    </Suspense>
  );
}
