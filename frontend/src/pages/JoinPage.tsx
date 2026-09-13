/**
 * 진입 — 초대 링크 착지 화면 (S0)
 *
 *   /interview/:sessionId      ← 명세의 inviteUrl 경로와 같다
 *
 * 지원자는 초대 링크에서 sessionId 를 전달받는다 (BE 명세 2026-09-08).
 * 사용자가 코드를 직접 입력하는 화면은 없어졌다 — 링크 자체가 자격증명이다.
 *
 * 여기서는 입장 권한만 확인한다. 카메라·마이크 권한은 다음 단계(기기 점검)에서 묻는다 —
 * 잘못된 링크가 권한 프롬프트보다 먼저 걸려야 하기 때문이다.
 */

import { useMutation } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { joinSession, toJoinFailure } from '../api/interview';
import type { JoinFailure, JoinSessionResponse, Role } from '../types/interview';

const FAILURE_MESSAGE: Record<JoinFailure, string> = {
  'not-found': '유효하지 않은 링크입니다. 면접관에게 링크를 다시 요청해주세요.',
  ended: '이미 종료된 면접입니다. 면접관에게 문의해주세요.',
  'room-full': '이미 다른 참가자가 입장해 있습니다. 면접관에게 문의해주세요.',
  // 409 인데 코드를 못 읽은 경우. 두 사유를 구분할 수 없으므로 합쳐서 안내한다.
  unavailable: '지금은 입장할 수 없습니다. 이미 종료되었거나 정원이 찼습니다.',
  failed: '입장하지 못했습니다. 잠시 후 다시 시도해주세요.',
};

export interface JoinPageProps {
  /**
   * 입장 권한. 초대 링크로 들어온 사람은 지원자다.
   *
   * ⚠️ 명세상 role 을 클라이언트가 선언한다 (인증 도입 전 임시 구조).
   * 면접관 진입 경로가 정해지면 그쪽에서 INTERVIEWER 를 넘긴다.
   */
  role: Role;
  /** 입장 성공 — 다음은 기기 점검 화면이다 */
  onJoined: (session: JoinSessionResponse) => void;
}

export default function JoinPage({ role, onJoined }: JoinPageProps) {
  const { sessionId } = useParams<{ sessionId: string }>();
  const join = useMutation({
    mutationFn: () => joinSession(sessionId!, role),
    onSuccess: onJoined,
  });

  const failure: JoinFailure | null = join.isError ? toJoinFailure(join.error) : null;

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
          onClick={() => join.mutate()}
          disabled={join.isPending}
          className="mt-2 w-full rounded-lg bg-[#2B44D6] py-3.5 text-[15px] font-medium text-white transition hover:bg-[#243AB8] disabled:bg-white/10 disabled:text-white/35"
        >
          {join.isPending ? '입장하는 중…' : '입장'}
        </button>

        <p className="mt-6 text-center font-mono text-[12px] break-all text-white/25">
          {sessionId}
        </p>
      </div>
    </div>
  );
}
