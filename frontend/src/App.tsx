/**
 * 개발환경 확인용 진입 화면.
 *
 * 실제 면접 화면(pages/InterviewRoom)은 아직 마운트하지 않는다 —
 * POST /interviews/{id}/start 가 BE #9 에서 만들어진 뒤에 붙인다.
 * 방 코드 입장 화면과 라우팅은 #5 · #8 범위다.
 *
 * ?mock=interview 로 접속하면 서버 없이 면접 화면을 볼 수 있다.
 */

import { InterviewRoomPreview } from './mocks/InterviewRoomPreview';

const API_BASE = import.meta.env.VITE_API_BASE ?? '(미설정 — api/client.ts 기본값 사용)';

export default function App() {
  if (new URLSearchParams(window.location.search).get('mock') === 'interview') {
    return <InterviewRoomPreview />;
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-lg">
        <h1 className="text-2xl font-semibold text-white">IRYA Frontend</h1>
        <p className="mt-2 text-[15px] text-white/60">개발환경이 정상 동작합니다.</p>

        <dl className="mt-6 rounded-xl bg-white/[0.06] p-5">
          <div className="flex gap-3 font-mono text-[13px]">
            <dt className="shrink-0 text-white/45">VITE_API_BASE</dt>
            <dd className="break-all text-white">{API_BASE}</dd>
          </div>
        </dl>

        <a
          href="?mock=interview"
          className="mt-6 inline-block rounded-md bg-[#2B44D6] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#243AB8]"
        >
          면접 화면 미리보기 (목 데이터)
        </a>

        <p className="mt-6 text-[13px] leading-relaxed text-white/45">
          면접 화면은 <code className="text-white/70">src/pages/InterviewRoom.tsx</code> 에
          있습니다. LiveKit 연결과 방 코드 입장 화면은 이슈 #5 · #8 에서 붙입니다.
        </p>
      </div>
    </div>
  );
}
