/**
 * 라우팅.
 *
 *   /                       안내 화면
 *   /context/:contextId     기업 컨텍스트 — 문서 업로드
 *   /host                   면접 준비 — 면접 생성 · 초대 링크 발급
 *   /interview/:sessionId   초대 링크 착지 — 입장 → 기기 점검 → 면접 화면
 *   /interview/:sessionId/summary  면접 종료 후 요약
 *   /review/:interviewId    면접 기록 — 녹화 · 타임라인 · AI 평가
 *   /mock/interview         면접 화면만 바로 보기 — 임시, 전사 연동 시 제거
 *
 * 경로는 명세의 inviteUrl(`https://irya.com/interview/ses_123`)과 맞췄다.
 */

import type { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import {
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import CompanyContextPage from './pages/CompanyContextPage';
import InterviewSetupPage from './pages/InterviewSetupPage';
import InterviewSummaryPage from './pages/InterviewSummaryPage';
import JoinPage from './pages/JoinPage';
import { INTERVIEWER_LABEL, loadCandidateName } from './lib/candidateName';
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
  videoTrack: LocalVideoTrack | null;
  audioTrack: LocalAudioTrack | null;
}

/**
 * 기기 점검을 통과할 때까지 자식을 그리지 않는다.
 *
 * 트랙 소유권 처리를 여기 한 곳에 모은다. usePermissionCheck 는 release() 를 부른 쪽에
 * 소유권을 넘기고 그 뒤로는 스스로 stop 하지 않는다. 프로토타입에는 publishTrack 이 없어
 * Room 이 대신 정리해 주지도 않으므로, 이 컴포넌트가 정리까지 책임진다.
 */
function DeviceGate({ children }: { children: (tracks: LocalTracks) => ReactNode }) {
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

  // 면접관만 지원자 이름을 본다. 지원자에게는 면접관 실명을 알려주지 않는다.
  const remoteName = role === 'INTERVIEWER' ? loadCandidateName(sessionId) : INTERVIEWER_LABEL;

  if (!session) {
    return <JoinPage role={role} onJoined={setSession} />;
  }

  // ⚠️ 프로토타입 — 전사·추천 질문은 목 데이터다 (WebSocket 경로가 명세에 없음).
  //    자기 화면(PiP)과 상대 영상 자리는 기기 점검에서 얻은 실제 트랙을 쓴다.
  return (
    <DeviceGate>
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
 * 안내 화면.
 *
 * 실제 서비스에서는 초대 링크로만 들어오므로 이 화면이 필요 없다.
 * 프로토타입 시연을 위해 두 역할의 진입점을 열어 둔다.
 */
function Landing() {
  const demoSession = 'ses_demo';

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold text-white">IRYA</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-white/60">
          실제 서비스에서는 면접관이 발급한 초대 링크로 입장합니다.
        </p>

        <div className="mt-7 flex flex-col gap-2.5">
          <Link
            to="/host"
            className="rounded-lg bg-[#2B44D6] px-5 py-3.5 text-center text-[15px] font-medium text-white transition hover:bg-[#243AB8]"
          >
            면접 만들기 (면접관)
          </Link>
          <Link
            to={`/interview/${demoSession}`}
            className="rounded-lg bg-white/[0.08] px-5 py-3.5 text-center text-[15px] font-medium text-white transition hover:bg-white/[0.13]"
          >
            지원자로 바로 입장 (링크 없이)
          </Link>
        </div>

        <p className="mt-7 text-[13px] leading-relaxed text-white/40">
          프로토타입입니다. 카메라·마이크와 기기 점검은 실제로 동작하고, 상대방 영상과 전사·추천
          질문은 목 데이터입니다.
        </p>

        <div className="mt-5 flex flex-col gap-1.5 text-[13px] text-white/30">
          <Link to="/interview/not-found?role=interviewer" className="hover:text-white/60">
            → 유효하지 않은 링크 화면 보기
          </Link>
          <Link to="/interview/ended?role=interviewer" className="hover:text-white/60">
            → 입장 불가 화면 보기
          </Link>
          <Link to="/review/int_demo" className="hover:text-white/60">
            → 면접 기록 화면 보기
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/context/:contextId" element={<CompanyContextPage />} />
      <Route path="/host" element={<InterviewSetupPage />} />
      <Route path="/interview/:sessionId" element={<InterviewFlow />} />
      <Route path="/interview/:sessionId/summary" element={<InterviewSummaryPage />} />
      <Route
        path="/review/:interviewId"
        element={
          <Suspense fallback={<ChunkFallback />}>
            <ReviewTimelinePage />
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
