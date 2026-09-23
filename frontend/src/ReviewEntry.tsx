import { lazy, Suspense } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import App from './App';

const CandidateListPage = lazy(() => import('./pages/CandidateListPage'));
const CandidateDetailPage = lazy(() => import('./pages/CandidateDetailPage'));
const CandidateMemoPage = lazy(() => import('./pages/CandidateMemoPage'));

export default function ReviewEntry() {
  const { pathname } = useLocation();

  if (pathname !== '/candidates' && !pathname.startsWith('/demo/candidates')) {
    return <App />;
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
