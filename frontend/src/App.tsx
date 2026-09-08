/**
 * 라우팅.
 *
 *   /interview/:sessionId   초대 링크 착지 — 입장 → 기기 점검 → 면접 화면
 *   /mock/interview         서버 없이 보는 면접 화면 — 임시, 전사 연동 시 제거
 *   /                       안내 화면
 *
 * 경로는 명세의 inviteUrl(`https://irya.com/interview/ses_123`)과 맞췄다.
 */

import { useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { InterviewRoomPreview } from './mocks/InterviewRoomPreview';
import DeviceCheckPage from './pages/DeviceCheckPage';
import JoinPage from './pages/JoinPage';
import type { JoinSessionResponse } from './types/interview';

/**
 * 진입 흐름 — join → 기기 점검 → 방 접속.
 *
 * 라우트를 나누지 않고 한 컴포넌트에서 단계를 넘긴다.
 * 기기 점검에서 얻은 트랙을 다음 단계로 그대로 넘겨야 하는데,
 * 라우트 경계를 넘기면 트랙 소유권 추적이 흐트러지기 때문이다.
 */
function InterviewFlow() {
  const [session, setSession] = useState<JoinSessionResponse | null>(null);
  const [checked, setChecked] = useState(false);

  if (!session) {
    // 초대 링크로 들어온 사람은 지원자다.
    return <JoinPage role="CANDIDATE" onJoined={setSession} />;
  }

  if (!checked) {
    return (
      <DeviceCheckPage
        onReady={() => {
          // TODO(#5): 확보한 트랙을 면접 화면으로 넘긴다.
          setChecked(true);
        }}
      />
    );
  }

  // TODO(#5): 실제 면접 화면. 지원자 화면 설계가 정해지면 역할별로 분기한다.
  return <InterviewRoomPreview />;
}

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
      <Route path="/interview/:sessionId" element={<InterviewFlow />} />
      <Route path="/mock/interview" element={<InterviewRoomPreview />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
