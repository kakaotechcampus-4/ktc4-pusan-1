/**
 * 라우팅.
 *
 *   /login                  면접관 로그인 (카카오)
 *   /oauth/kakao/callback   카카오 콜백 — code 를 토큰으로 바꾼다
 *   /                       메인 — 면접 만들기 입구
 *   /settings/context       기업 컨텍스트 설정 — 조직당 하나, 모든 면접에 적용
 *   /interviews/new         면접 만들기 — 지원자 정보 · 이력서 · 초대 링크
 *   /interview/:sessionId   초대 링크 착지 — 입장 → 기기 점검 → 면접 화면
 *   /interview/:sessionId/summary  면접 종료 후 요약
 *   /review/:interviewId    면접 기록 — 녹화 · 타임라인 · AI 평가
 *   /mock/interview         개발용 목 면접 미리보기
 *
 * 경로는 명세의 inviteUrl(`https://irya.com/interview/ses_123`)과 맞췄다.
 */

import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import ContextSettingsPage from './pages/ContextSettingsPage';
import InterviewCreatePage from './pages/InterviewCreatePage';
import InterviewSummaryPage from './pages/InterviewSummaryPage';
import JoinPage from './pages/JoinPage';
import KakaoCallbackPage from './pages/KakaoCallbackPage';
import LoginPage from './pages/LoginPage';
import MainPage from './pages/MainPage';
import { getMe } from './api/auth';
import { ApiError } from './api/client';
import { useAccessToken } from './hooks/useAccessToken';
import { USE_MOCK_API } from './mocks/mockApi';
import { InterviewerHeader } from './components/layout/InterviewerHeader';
import { FALLBACK_CANDIDATE, INTERVIEWER_LABEL } from './lib/candidateName';
import type { JoinSessionResponse, Role } from './types/interview';

/* 카메라·마이크를 쓰는 화면만 따로 내려받는다.
   livekit-client 가 번들의 대부분을 차지하는데, 진입·요약 화면에는 필요 없다.
   이렇게 나누면 링크를 연 사람이 첫 화면을 보기까지 받는 양이 줄어든다. */
const InterviewRoom = lazy(() => import('./pages/InterviewRoom'));
const CandidateListPage = lazy(() => import('./pages/CandidateListPage'));
const CandidateDetailPage = lazy(() => import('./pages/CandidateDetailPage'));
const CandidateMemoPage = lazy(() => import('./pages/CandidateMemoPage'));
const DeviceCheckPage = lazy(() => import('./pages/DeviceCheckPage'));
// hls.js 도 크다. 면접 기록을 여는 사람만 받는다.
const ReviewTimelinePage = lazy(() => import('./pages/ReviewTimelinePage'));
const InterviewRoomPreview = lazy(() =>
  import('./mocks/InterviewRoomPreview').then((m) => ({ default: m.InterviewRoomPreview })),
);

/** 청크를 받는 동안 잠깐 보인다. 배경색만 맞춰 깜빡임을 줄인다. */
function ChunkFallback() {
  return <div className="h-screen w-screen bg-[#0B0E14]" />;
}

interface LocalTracks {
  videoTrack: MediaStreamTrack | null;
  audioTrack: MediaStreamTrack | null;
}

/**
 * 기기 점검을 통과할 때까지 자식을 그리지 않는다.
 *
 * 트랙 소유권 처리를 여기 한 곳에 모은다. usePermissionCheck 는 release() 를 부른 쪽에
 * 소유권을 넘기고 그 뒤로는 스스로 stop 하지 않는다. Room은 disconnect(false)로
 * 원본 트랙을 유지하고, 최종 정리는 이 컴포넌트가 책임진다.
 */
function DeviceGate({
  children,
  livekitConnection,
  onBack,
}: {
  children: (tracks: LocalTracks) => ReactNode;
  livekitConnection?: Pick<JoinSessionResponse, 'livekitUrl' | 'token'>;
  onBack?: () => void;
}) {
  const [tracks, setTracks] = useState<LocalTracks | null>(null);

  useEffect(() => {
    if (!tracks) return;
    return () => {
      tracks.videoTrack?.stop();
      tracks.audioTrack?.stop();
    };
  }, [tracks]);

  if (!tracks) {
    return (
      <Suspense fallback={<ChunkFallback />}>
        <DeviceCheckPage
          livekitConnection={livekitConnection}
          onBack={onBack}
          onReady={({ videoTrack, audioTrack, release }) => {
            // release() 를 부르지 않으면 DeviceCheckPage 가 언마운트되면서
            // usePermissionCheck 의 정리가 트랙을 stop 한다 — 다음 화면에 죽은 트랙이 넘어간다.
            release();
            setTracks({ videoTrack, audioTrack });
          }}
        />
      </Suspense>
    );
  }

  return <>{children(tracks)}</>;
}

/**
 * 진입 흐름 — join → 기기 점검 → 면접 화면.
 *
 * 라우트를 나누지 않고 한 컴포넌트에서 단계를 넘긴다.
 * 기기 점검에서 얻은 트랙을 다음 단계로 그대로 넘겨야 하는데,
 * 라우트 경계를 넘기면 트랙 소유권 추적이 흐트러지기 때문이다.
 */
function InterviewFlow() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<JoinSessionResponse | null>(null);

  // 명세상 role 은 클라이언트가 선언한다 (인증 도입 전 임시 구조).
  // 초대 링크로 들어오면 지원자, `?role=interviewer` 면 면접관이다.
  // ⚠️ 서버가 역할을 판단하도록 바뀌면 이 파라미터는 사라진다.
  const [searchParams] = useSearchParams();
  const role: Role = searchParams.get('role') === 'interviewer' ? 'INTERVIEWER' : 'CANDIDATE';

  // 면접관만 서버에 저장된 지원자 이름을 본다. 지원자에게는 면접관 실명을 알려주지 않는다.
  const remoteName =
    role === 'INTERVIEWER' ? (session?.candidateName ?? FALLBACK_CANDIDATE) : INTERVIEWER_LABEL;

  if (!sessionId) return <Navigate to="/" replace />;

  if (!session) {
    return <JoinPage role={role} onJoined={setSession} />;
  }

  const onEnded = () => {
    // 지원자는 계정이 없어 로그인 화면 대신 같은 초대 링크로 돌아가 재입장할 수 있다.
    void navigate(
      role === 'INTERVIEWER' ? `/interview/${sessionId}/summary` : `/interview/${sessionId}`,
      { replace: true },
    );
    setSession(null);
  };

  return (
    <DeviceGate
      livekitConnection={USE_MOCK_API ? undefined : session}
      // 지원자는 계정이 없으므로 점검을 취소해도 초대 링크 안에서 다시 입장한다.
      onBack={role === 'CANDIDATE' ? () => setSession(null) : undefined}
    >
      {(tracks) => (
        <Suspense fallback={<ChunkFallback />}>
          {USE_MOCK_API ? (
            <InterviewRoomPreview
              role={role}
              sessionId={sessionId}
              remoteName={remoteName}
              localVideoTrack={tracks.videoTrack}
              localAudioTrack={tracks.audioTrack}
              onLeave={onEnded}
            />
          ) : (
            <InterviewRoom
              sessionId={sessionId}
              role={role}
              remoteName={remoteName}
              videoTrack={tracks.videoTrack}
              audioTrack={tracks.audioTrack}
              onEnded={onEnded}
            />
          )}
        </Suspense>
      )}
    </DeviceGate>
  );
}

/** 지원자 초대 링크는 공개하고 면접관 입장만 인증한다. */
function InterviewEntry() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [params] = useSearchParams();
  const interviewer = params.get('role') === 'interviewer';
  const flow = <InterviewFlow key={`${sessionId}/${interviewer}`} />;
  return interviewer ? <RequireAuth>{flow}</RequireAuth> : flow;
}

/** 업무 화면에서 어디서든 목록·설정·새 면접으로 이동할 수 있다. */
function InterviewerPage({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <InterviewerHeader />
      <Suspense fallback={<ChunkFallback />}>{children}</Suspense>
    </RequireAuth>
  );
}

/**
 * 로그인해야 볼 수 있는 화면을 감싼다.
 *
 * 지원자 경로(초대 링크)는 감싸지 않는다 — 지원자는 회사 사람이 아니라 계정이 없다.
 */
function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const token = useAccessToken();
  const hasToken = Boolean(token);

  // 토큰이 있어도 쓸 수 있는지는 서버만 안다. 만료·위조면 401 이 오고, 그때 버린다.
  // 이 확인 없이 들여보내면 화면마다 따로 401 을 만나 어디서 튕겼는지 알 수 없다.
  const { isLoading, isError, error, refetch } = useQuery({
    queryKey: ['me', token],
    queryFn: getMe,
    enabled: hasToken,
    retry: false,
    // 한 번 확인했으면 화면을 옮길 때마다 다시 묻지 않는다.
    staleTime: 5 * 60 * 1000,
  });

  const expired = isError && error instanceof ApiError && error.status === 401;

  if (!hasToken || expired)
    return (
      <Navigate
        to="/login"
        replace
        state={{ returnTo: `${location.pathname}${location.search}${location.hash}` }}
      />
    );
  // 확인이 끝나기 전에 화면을 그리면 로그인 화면이 깜빡였다가 사라진다.
  if (isLoading) return <ChunkFallback />;
  if (isError) {
    return (
      <div className="bg-surface text-ink flex min-h-screen flex-col items-center justify-center gap-4">
        <p>로그인 상태를 확인하지 못했습니다.</p>
        <button type="button" onClick={() => void refetch()}>
          다시 확인
        </button>
      </div>
    );
  }
  // 계정이 바뀌면 이전 계정에서 쓰던 입력값과 화면 상태도 함께 정리한다.
  return <Suspense key={token}>{children}</Suspense>;
}

export default function App() {
  const navigate = useNavigate();
  useAccessToken();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/oauth/kakao/callback" element={<KakaoCallbackPage />} />
      <Route
        path="/"
        element={
          <InterviewerPage>
            <MainPage />
          </InterviewerPage>
        }
      />
      <Route
        path="/settings/context"
        element={
          <InterviewerPage>
            <ContextSettingsPage />
          </InterviewerPage>
        }
      />
      <Route
        path="/interviews/new"
        element={
          <InterviewerPage>
            <InterviewCreatePage />
          </InterviewerPage>
        }
      />
      <Route path="/interview/:sessionId" element={<InterviewEntry />} />
      <Route
        path="/interview/:sessionId/summary"
        element={
          <InterviewerPage>
            <InterviewSummaryPage />
          </InterviewerPage>
        }
      />
      <Route
        path="/review/:interviewId"
        element={
          <InterviewerPage>
            <Suspense fallback={<ChunkFallback />}>
              <ReviewTimelinePage />
            </Suspense>
          </InterviewerPage>
        }
      />
      <Route
        path="/candidates"
        element={
          <InterviewerPage>
            <CandidateListPage />
          </InterviewerPage>
        }
      />
      <Route
        path="/demo/candidates"
        element={
          <Suspense fallback={<ChunkFallback />}>
            <CandidateListPage demo />
          </Suspense>
        }
      />
      <Route
        path="/demo/candidates/:candidateId"
        element={
          <Suspense fallback={<ChunkFallback />}>
            <CandidateDetailPage />
          </Suspense>
        }
      />
      <Route
        path="/demo/candidates/:candidateId/memo"
        element={
          <Suspense fallback={<ChunkFallback />}>
            <CandidateMemoPage />
          </Suspense>
        }
      />
      <Route
        path="/mock/interview"
        element={
          <DeviceGate>
            {(tracks) => (
              <Suspense fallback={<ChunkFallback />}>
                <InterviewRoomPreview
                  localVideoTrack={tracks.videoTrack}
                  localAudioTrack={tracks.audioTrack}
                  onLeave={() => void navigate('/')}
                />
              </Suspense>
            )}
          </DeviceGate>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
