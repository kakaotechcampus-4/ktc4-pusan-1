/**
 * 진입 — 초대 링크 착지 화면 (S0)
 *
 *   /sessions/:sessionId/join
 *
 * 지원자는 초대 링크에서 sessionId 를 전달받는다 (BE 명세 2026-09-08).
 * 사용자가 코드를 직접 입력하는 화면은 없어졌다 — 링크 자체가 자격증명이다.
 *
 * 여기서는 입장 권한만 확인한다. 카메라·마이크 권한은 다음 단계(기기 점검)에서 묻는다 —
 * 잘못된 링크가 권한 프롬프트보다 먼저 걸려야 하기 때문이다.
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { joinSession, toJoinFailure } from '../api/interview';
import type { JoinFailure, JoinSessionResponse } from '../types/interview';

const FAILURE_MESSAGE: Record<JoinFailure, string> = {
  'not-found': '유효하지 않은 링크입니다. 면접관에게 링크를 다시 요청해주세요.',
  forbidden: '이 면접에 입장할 권한이 없습니다.',
  ended: '이미 종료된 면접입니다.',
  full: '이미 두 명이 입장해 있어 들어갈 수 없습니다.',
  failed: '입장하지 못했습니다. 잠시 후 다시 시도해주세요.',
};

export interface JoinPageProps {
  /** 입장 성공 — 다음은 기기 점검 화면이다 */
  onJoined: (session: JoinSessionResponse) => void;
}

export default function JoinPage({ onJoined }: JoinPageProps) {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [failure, setFailure] = useState<JoinFailure | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleJoin = async () => {
    if (!sessionId || submitting) return;

    setSubmitting(true);
    setFailure(null);
    try {
      onJoined(await joinSession(sessionId));
    } catch (err) {
      setFailure(toJoinFailure(err));
    } finally {
      setSubmitting(false);
    }
  };

  // 링크에 sessionId 가 없으면 입장 자체가 불가능하다.
  if (!sessionId) {
    return (
      <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
        <div className="w-full max-w-md text-center">
          <h1 className="text-2xl font-semibold text-white">유효하지 않은 링크입니다</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-white/60">
            면접관에게 받은 초대 링크를 그대로 열어주세요.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold text-white">면접 입장</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-white/60">
          입장하면 카메라와 마이크 사용 권한을 요청합니다.
        </p>

        <div aria-live="polite" className="mt-6 min-h-[24px]">
          {failure && <p className="text-sm text-[#FF8A8A]">{FAILURE_MESSAGE[failure]}</p>}
        </div>

        <button
          type="button"
          onClick={() => void handleJoin()}
          disabled={submitting}
          className="mt-2 w-full rounded-lg bg-[#2B44D6] py-3.5 text-[15px] font-medium text-white transition hover:bg-[#243AB8] disabled:bg-white/10 disabled:text-white/35"
        >
          {submitting ? '입장하는 중…' : '입장'}
        </button>

        <p className="mt-6 text-center font-mono text-[12px] break-all text-white/25">
          {sessionId}
        </p>
      </div>
    </div>
  );
}
