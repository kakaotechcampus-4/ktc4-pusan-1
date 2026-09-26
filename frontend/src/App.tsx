/**
 * 라우팅.
 *
 *   /login                  면접관 로그인
 *   /                       메인 — 면접 만들기 입구
 *   /settings/context       기업 컨텍스트 설정 — 조직당 하나, 모든 면접에 적용
 *   /interviews/new         면접 만들기 — 지원자 정보 · 이력서 · 초대 링크
 *   /interview/:sessionId   초대 링크 착지 — 입장 → 기기 점검 → 면접 화면
 *   /interview/:sessionId/summary  면접 종료 후 요약
 *   /review/:interviewId    면접 기록 — 녹화 · 타임라인 · AI 평가
 *   /mock/interview         면접 화면만 바로 보기 — 임시, 전사 연동 시 제거
 *
 * 경로는 명세의 inviteUrl(`https://irya.com/interview/ses_123`)과 맞췄다.
 */

import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { Navigate, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ContextSettingsPage from './pages/ContextSettingsPage';
import InterviewCreatePage from './pages/InterviewCreatePage';
import InterviewSummaryPage from './pages/InterviewSummaryPage';
import JoinPage from './pages/JoinPage';
import LoginPage from './pages/LoginPage';
import MainPage from './pages/MainPage';
import { readAccessToken } from './lib/authToken';
import { FALLBACK_CANDIDATE, INTERVIEWER_LABEL } from './lib/candidateName';
import type { JoinSessionResponse, Role } from './types/interview';

/* 카메라·마이크를 쓰는 화면만 따로 내려받는다.
   livekit-client 가 번들의 대부분을 차지하는데, 진입·요약 화면에는 필요 없다.
   이렇게 나누면 링크를 연 사람이 첫 화면을 보기까지 받는 양이 줄어든다. */
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
 * 소유권을 넘기고 그 뒤로는 스스로 stop 하지 않는다. 프로토타입에는 publishTrack 이 없어
 * Room 이 대신 정리해 주지도 않으므로, 이 컴포넌트가 정리까지 책임진다.
 */
function DeviceGate({
  children,
  livekitConnection,
}: {
  children: (tracks: LocalTracks) => ReactNode;
  livekitConnection?: Pick<JoinSessionResponse, 'livekitUrl' | 'token'>;
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

  if (!session) {
    return <JoinPage role={role} onJoined={setSession} />;
  }

  // ⚠️ 프로토타입 — 전사·추천 질문은 목 데이터다 (WebSocket 경로가 명세에 없음).
  //    자기 화면(PiP)과 상대 영상 자리는 기기 점검에서 얻은 실제 트랙을 쓴다.
  return (
    <DeviceGate livekitConnection={session}>
      {(tracks) => (
        <Suspense fallback={<ChunkFallback />}>
          <InterviewRoomPreview
            role={role}
            sessionId={sessionId}
            remoteName={remoteName}
            localVideoTrack={tracks.videoTrack}
            localAudioTrack={tracks.audioTrack}
            onLeave={() => {
              // 면접관은 요약을 본다. 지원자는 요약 열람 권한이 없으므로 처음으로 돌아간다.
              void navigate(role === 'INTERVIEWER' ? `/interview/${sessionId}/summary` : '/');
            }}
          />
        </Suspense>
      )}
    </DeviceGate>
  );
}

/**
 * 로그인해야 볼 수 있는 화면을 감싼다.
 *
 * 지원자 경로(초대 링크)는 감싸지 않는다 — 지원자는 회사 사람이 아니라 계정이 없다.
 */
function RequireAuth({ children }: { children: ReactNode }) {
  if (!readAccessToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainPage />
          </RequireAuth>
        }
      />
      <Route
        path="/settings/context"
        element={
          <RequireAuth>
            <ContextSettingsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/interviews/new"
        element={
          <RequireAuth>
            <InterviewCreatePage />
          </RequireAuth>
        }
      />
      <Route path="/interview/:sessionId" element={<InterviewFlow />} />
      <Route
        path="/interview/:sessionId/summary"
        element={
          <RequireAuth>
            <InterviewSummaryPage />
          </RequireAuth>
        }
      />
      <Route
        path="/review/:interviewId"
        element={
          <RequireAuth>
            <Suspense fallback={<ChunkFallback />}>
              <ReviewTimelinePage />
            </Suspense>
          </RequireAuth>
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
