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
import type { ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { joinSession, toJoinFailure } from '../api/interview';
import deviceCheckImg from '../assets/illustrations/device-check.webp';
import { buttonClass } from '../components/ui/buttonClass';
import { Logo } from '../components/ui/Logo';
import type { JoinFailure, JoinSessionResponse, Role } from '../types/interview';

const FAILURE_MESSAGE: Record<JoinFailure, string> = {
  'consent-required':
    '녹화 · 전사 · 분석 동의가 저장되지 않았습니다. 받으신 링크를 다시 열어 동의해주세요.',
  'not-found': '유효하지 않은 링크입니다. 면접관에게 링크를 다시 요청해주세요.',
  // 다시 눌러도 같다 — 계정을 바꾸거나 지원자로 들어와야 한다.
  'not-allowed':
    '이 면접의 면접관만 면접관으로 입장할 수 있습니다. 로그인한 계정을 확인해주세요. 지원자라면 받으신 초대 링크로 들어와주세요.',
  // 토큰이 만료돼 이미 지워졌다. 「잠시 후 다시」로 묶으면 눌러도 영원히 같다.
  'signed-out': '로그인이 만료되었습니다. 다시 로그인한 뒤 면접관으로 입장해주세요.',
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
      <Frame>
        <h1 className="text-ink text-[24px] font-bold">유효하지 않은 링크입니다</h1>
        <p className="text-ink-muted mt-2 text-[15px] leading-relaxed">
          면접관에게 받은 초대 링크를 그대로 열어주세요.
        </p>
      </Frame>
    );
  }

  return (
    <Frame>
      <img
        src={deviceCheckImg}
        alt=""
        width={1200}
        height={800}
        className="mx-auto -mt-2 mb-2 w-full max-w-[320px]"
      />
      <h1 className="text-ink text-[24px] font-bold tracking-tight">
        {role === 'INTERVIEWER' ? '면접관으로 입장합니다' : '화상 면접에 입장합니다'}
      </h1>
      <p className="text-ink-muted mt-2 text-[15px] leading-relaxed">
        입장하면 카메라와 마이크 사용 권한을 요청합니다. 다음 화면에서 기기를 점검한 뒤 면접방에
        들어갑니다.
      </p>

      <div aria-live="polite" className="mt-5 min-h-[24px]">
        {failure && (
          <p className="bg-danger-tint text-danger rounded-xl px-4 py-3 text-left text-[14px]">
            {FAILURE_MESSAGE[failure]}
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={() => join.mutate()}
        disabled={join.isPending}
        className={`${buttonClass('primary', 'lg')} mt-2 w-full`}
      >
        {join.isPending ? '입장하는 중…' : '입장하기'}
      </button>

      <p className="text-ink-dim mt-6 font-mono text-[12px] break-all">{sessionId}</p>
    </Frame>
  );
}

/** 로그인 없이 여는 화면이라 앱 틀 없이 가운데 카드 하나로 그린다. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="from-brand-tint via-surface flex min-h-full flex-col items-center justify-center gap-6 bg-gradient-to-b to-[#effbf8] p-5">
      <Logo />
      <main className="border-border-base bg-surface-panel shadow-card w-full max-w-md rounded-3xl border p-7 text-center sm:p-8">
        {children}
      </main>
    </div>
  );
}
