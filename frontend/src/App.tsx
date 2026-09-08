/**
 * 라우팅.
 *
 *   /join              방 코드 입력 (?code= 로 프리필)
 *   /mock/interview    서버 없이 보는 면접 화면 — 임시, #5 착수 시 제거
 *   /                  /join 으로
 *
 * 면접 화면(/room)은 아직 라우트에 없다. join 응답 스키마가 확정되지 않아
 * 입장 성공 후 넘길 값이 정해지지 않았기 때문이다 (issue #9).
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

export default function App() {
  return (
    <Routes>
      <Route path="/join" element={<JoinRoute />} />
      <Route path="/mock/interview" element={<InterviewRoomPreview />} />
      <Route path="*" element={<Navigate to="/join" replace />} />
    </Routes>
  );
}
