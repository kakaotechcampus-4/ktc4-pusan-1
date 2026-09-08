/**
 * 라우팅.
 *
 *   /sessions/:sessionId/join   초대 링크 착지 — 입장 권한 확인
 *   /mock/interview             서버 없이 보는 면접 화면 — 임시, #5 착수 시 제거
 *   /                           안내 화면 (직접 들어온 경우)
 *
 * 면접 화면(/sessions/:id/room)은 아직 라우트에 없다.
 * join 응답 본문이 명세에 없어 입장 성공 후 넘길 값이 정해지지 않았다.
 */

import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { InterviewRoomPreview } from './mocks/InterviewRoomPreview';
import JoinPage from './pages/JoinPage';

function JoinRoute() {
  const navigate = useNavigate();

  return (
    <JoinPage
      onJoined={(session) => {
        // 다음은 기기 점검 화면이다. 아직 없으므로 목 미리보기로 보낸다.
        // 실제 연결은 #5 에서 붙인다.
        console.info('join 성공', session.role, session.sessionId);
        void navigate('/mock/interview');
      }}
    />
  );
}

/** 링크 없이 루트로 들어온 경우. 면접관 진입(S1)은 아직 없다. */
function Landing() {
  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-md text-center">
        <h1 className="text-2xl font-semibold text-white">IRYA</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-white/60">
          면접관에게 받은 초대 링크로 입장해주세요.
        </p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/sessions/:sessionId/join" element={<JoinRoute />} />
      <Route path="/mock/interview" element={<InterviewRoomPreview />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
