/**
 * 면접 준비 — 면접 생성과 초대 링크 발급 (면접관)
 *
 * 명세상 두 단계다.
 *   POST /api/v1/interviews                      면접 정보 생성
 *   POST /api/v1/interviews/{id}/sessions        Session 생성 + 초대 링크 발급
 *
 * 사용자에게는 한 번의 동작으로 보이므로 버튼 하나로 묶는다.
 * 두 요청 사이에서 실패하면 면접만 만들어지고 Session 이 없는 상태가 되는데,
 * 그때는 다시 누르면 새 면접이 생긴다 — 프로토타입에서는 이 정도로 둔다.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { createInterview, createSession } from '../api/interview';
import type { CreateSessionResponse } from '../types/interview';

/** ⚠️ 인증이 없어 면접관 ID 를 클라이언트가 정한다. 로그인 도입 시 사라진다. */
const MOCK_INTERVIEWER_ID = 'user_demo';

export default function InterviewSetupPage() {
  const [session, setSession] = useState<CreateSessionResponse | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const interview = await createInterview(MOCK_INTERVIEWER_ID);
      setSession(await createSession(interview.interviewId));
    } catch {
      setError('면접을 만들지 못했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setCreating(false);
    }
  };

  const handleCopy = async () => {
    if (!session) return;
    try {
      await navigator.clipboard.writeText(session.inviteUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 클립보드 권한이 없거나 보안 컨텍스트가 아니면 실패한다.
      // 링크는 화면에 그대로 보이므로 직접 선택해 복사할 수 있다.
      setError('자동 복사에 실패했습니다. 링크를 직접 선택해 복사해주세요.');
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-lg">
        <h1 className="text-2xl font-semibold text-white">면접 준비</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-white/60">
          면접을 만들면 지원자에게 보낼 초대 링크가 발급됩니다.
        </p>

        {!session && (
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={creating}
            className="mt-7 w-full rounded-lg bg-[#2B44D6] py-3.5 text-[15px] font-medium text-white transition hover:bg-[#243AB8] disabled:bg-white/10 disabled:text-white/35"
          >
            {creating ? '만드는 중…' : '면접 만들기'}
          </button>
        )}

        {session && (
          <>
            <dl className="mt-7 rounded-xl bg-white/[0.06] p-5 font-mono text-[13px]">
              <div className="flex gap-3">
                <dt className="w-24 shrink-0 text-white/45">면접 ID</dt>
                <dd className="text-white">{session.interviewId}</dd>
              </div>
              <div className="mt-2 flex gap-3">
                <dt className="w-24 shrink-0 text-white/45">Session ID</dt>
                <dd className="text-white">{session.sessionId}</dd>
              </div>
              <div className="mt-2 flex gap-3">
                <dt className="w-24 shrink-0 text-white/45">상태</dt>
                <dd className="text-[#FFC46B]">{session.status}</dd>
              </div>
            </dl>

            <p className="mt-6 text-[15px] font-medium text-white">지원자 초대 링크</p>
            <div className="mt-2 flex gap-2">
              <input
                readOnly
                value={session.inviteUrl}
                aria-label="지원자 초대 링크"
                onFocus={(e) => e.currentTarget.select()}
                className="min-w-0 flex-1 rounded-lg bg-white/[0.07] px-4 py-3 font-mono text-[13px] text-white"
              />
              <button
                type="button"
                onClick={() => void handleCopy()}
                className="shrink-0 rounded-lg bg-white/[0.12] px-4 py-3 text-sm font-medium text-white transition hover:bg-white/[0.18]"
              >
                {copied ? '복사됨' : '복사'}
              </button>
            </div>
            <p className="mt-2 text-[13px] text-white/40">
              이 링크를 다른 탭이나 다른 기기에서 열면 지원자로 입장합니다.
            </p>

            <Link
              to={`/interview/${session.sessionId}?role=interviewer`}
              className="mt-7 block rounded-lg bg-[#2B44D6] py-3.5 text-center text-[15px] font-medium text-white transition hover:bg-[#243AB8]"
            >
              면접방 입장
            </Link>
          </>
        )}

        <div aria-live="polite" className="mt-4 min-h-[20px]">
          {error && <p className="text-sm text-[#FF8A8A]">{error}</p>}
        </div>
      </div>
    </div>
  );
}
