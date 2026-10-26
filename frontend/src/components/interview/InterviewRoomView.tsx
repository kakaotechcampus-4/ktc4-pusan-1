/**
 * 면접 중 화면(S2)의 표현부.
 *
 * 라이트 테마에 맞춰(#232) 위에 상태 막대, 가운데 상대 영상 무대, 오른쪽에 면접관
 * 도구(꼬리질문 · 자동 기록)를 둔다. 자기 화면은 무대 오른쪽 아래에 작게 띄운다.
 *
 * 역할에 따라 얹는 것이 다르다.
 *
 *   면접관  전사 · 꼬리질문 · 면접 종료
 *   지원자  없음 · 나가기
 *
 * 지원자에게는 전사를 감춘다. 본인 발화가 실시간으로 받아적히는 것을 보면 답변이 위축된다.
 *
 * 연결(LiveKit·API)은 여기서 다루지 않는다 — pages/InterviewRoom 이 담당한다.
 * 덕분에 서버 없이도 이 화면만 따로 띄워 확인할 수 있다.
 */

import { ConnectionState } from 'livekit-client';
import { useEffect, useState, type RefObject } from 'react';
import { fmt } from '../../lib/format';
import type { Role } from '../../types/interview';
import { useInterviewStore } from '../../stores/interviewStore';
import { buttonClass } from '../ui/buttonClass';
import { Logo } from '../ui/Logo';
import { LocalPreview } from './LocalPreview';
import { SpeakerBadge } from './SpeakerBadge';
import { SuggestionPanel } from './SuggestionPanel';
import { TranscriptPanel } from './TranscriptPanel';

export interface InterviewRoomViewProps {
  /** 내 역할. 화면에 무엇을 얹을지 결정한다 */
  role: Role;
  /** 상대 이름. 면접관에겐 지원자 이름, 지원자에겐 면접관 이름이다 */
  remoteName: string;
  videoRef: RefObject<HTMLVideoElement | null>;
  audioRef: RefObject<HTMLAudioElement | null>;
  /** 연결 실패 코드. null 이면 정상 */
  error: string | null;
  /** 종료·나가기 요청 진행 중 */
  ending: boolean;
  /** 면접관이면 면접 종료, 지원자면 나가기 */
  onEnd: () => void;
  /** 자기 화면(PiP). 둘 다 없으면 PiP 를 그리지 않는다 */
  localVideoTrack?: MediaStreamTrack | null;
  localAudioTrack?: MediaStreamTrack | null;
  /**
   * 화면 하단에 띄울 안내. 프로토타입에서 무엇이 실제가 아닌지 밝히는 데 쓴다.
   * 시연 중 질문을 받기 전에 화면이 먼저 답하도록 한다.
   */
  notice?: string;
}

export function InterviewRoomView({
  role,
  remoteName,
  videoRef,
  audioRef,
  error,
  ending,
  onEnd,
  localVideoTrack,
  localAudioTrack,
  notice,
}: InterviewRoomViewProps) {
  const connection = useInterviewStore((s) => s.connection);
  const remoteJoined = useInterviewStore((s) => s.remoteJoined);
  const [elapsed, setElapsed] = useState(0);

  const isInterviewer = role === 'INTERVIEWER';
  // 시안의 붉은 REC 자리다. 녹화 여부는 화면이 알 수 없으므로 통화가 실제로
  // 오가는 중인지만 말한다 — 모르는 것을 켜 두면 표시가 거짓말이 된다.
  const live = !error && remoteJoined && connection === ConnectionState.Connected;

  useEffect(() => {
    if (connection !== 'connected') return;
    const t = setInterval(() => setElapsed((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [connection]);

  return (
    // 영상은 가운데 무대에 두고, 위에 상태 막대 · 오른쪽에 면접관 도구를 둔다 (#232).
    // 영상 위에 유리판을 얹던 시안과 달리 패널이 영상을 가리지 않는다.
    <div className="bg-surface text-ink flex h-screen w-screen flex-col gap-3 overflow-hidden p-3 sm:p-4">
      <audio ref={audioRef} autoPlay />

      {/* 위 — 상대, 진행 상태, 종료 */}
      <header className="border-border-base bg-surface-panel shadow-card flex shrink-0 items-center gap-3 rounded-2xl border px-3 py-2.5 sm:px-4">
        {/* 좁은 화면에서는 상대 이름 · 시간이 먼저라 로고를 뺀다 */}
        <span className="hidden sm:block">
          <Logo size="sm" />
        </span>
        <span aria-hidden className="bg-border-base hidden h-6 w-px sm:block" />
        {/* 프로필 사진 자리. 우리에겐 사진이 없어 이름 첫 글자로 자리를 지킨다 */}
        <span className="bg-brand-tint text-brand flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[14px] font-bold">
          {remoteName.slice(0, 1)}
        </span>
        <span className="min-w-0 truncate text-[15px] font-semibold">{remoteName}</span>

        <div className="flex shrink-0 items-center gap-2.5">
          {live && (
            <span className="bg-danger-tint text-danger inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold">
              <span className="bg-danger h-2 w-2 animate-pulse rounded-full" />
              LIVE
            </span>
          )}
          <span className="font-mono text-[15px] font-bold tracking-wider tabular-nums">
            {fmt(elapsed)}
          </span>
        </div>

        <span className="hidden md:block">
          <SpeakerBadge />
        </span>

        <span className="flex-1" />

        {/* 면접관만 면접을 끝낼 수 있다. 지원자는 자기 연결만 끊는다 —
            지원자가 나가도 세션은 살아 있어야 재입장할 수 있다. */}
        <button
          type="button"
          onClick={onEnd}
          disabled={ending}
          title={isInterviewer ? '면접 종료' : '나가기'}
          aria-label={isInterviewer ? '면접 종료' : '나가기'}
          className={buttonClass(isInterviewer ? 'danger' : 'secondary', 'sm')}
        >
          <span aria-hidden className="material-symbols-outlined text-[18px]">
            {isInterviewer ? 'call_end' : 'logout'}
          </span>
          <span className="hidden sm:inline">{isInterviewer ? '면접 종료' : '나가기'}</span>
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        {/* 무대 — 상대 영상. 영상은 어두운 바탕에 두어야 가장자리가 뜨지 않는다 */}
        <main
          className={`relative min-h-0 flex-1 overflow-hidden rounded-2xl ${
            remoteJoined && !error
              ? 'bg-[#0e1220]'
              : 'border-border-base bg-surface-container border'
          }`}
        >
          <video
            ref={videoRef}
            autoPlay
            playsInline
            className="absolute inset-0 h-full w-full object-cover"
          />

          {/* 상대 미참가 / 연결 중 / 실패 */}
          {(!remoteJoined || error) && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center">
              {error ? (
                <span className="bg-danger-tint text-danger flex h-14 w-14 items-center justify-center rounded-full">
                  <span aria-hidden className="material-symbols-outlined text-[28px]">
                    wifi_off
                  </span>
                </span>
              ) : (
                <span
                  aria-hidden
                  className="border-brand-tint border-t-brand h-10 w-10 animate-spin rounded-full border-4"
                />
              )}
              <p className="text-[18px] font-semibold">
                {error
                  ? '통화에 연결할 수 없습니다'
                  : connection === 'connected'
                    ? // 면접관은 지원자 이름을 알지만, 지원자는 면접관 이름을 모를 수 있다.
                      `${remoteName} 님을 기다리고 있습니다`
                    : '연결 중'}
              </p>
              {error ? (
                <p className="text-ink-dim font-mono text-sm">{error}</p>
              ) : (
                connection === 'connected' && (
                  <p className="text-ink-muted text-[14px]">
                    입장하면 이 자리에 화면이 나타납니다. 그동안 오른쪽 아래 내 화면을 확인해주세요.
                  </p>
                )
              )}
            </div>
          )}

          {/* 상대 이름표 — 영상이 보일 때만 */}
          {remoteJoined && !error && (
            <span className="absolute top-3 left-3 rounded-lg bg-black/55 px-2.5 py-1 text-[13px] font-medium text-white backdrop-blur-md">
              {remoteName}
            </span>
          )}

          {/* 자기 화면 — 대기 화면보다 뒤에 두어 그 위에 그려진다.
              상대를 기다리는 동안 자기 카메라 · 마이크를 점검하는 것이 목적이다.
              클릭을 가로채지 않도록 pointer-events 를 끈다. */}
          {(localVideoTrack || localAudioTrack) && (
            // 위치는 래퍼가 잡는다. LocalPreview 는 자기 루트에 relative 를 두므로
            // 여기서 absolute 를 같이 넘기면 두 position 유틸리티가 충돌한다.
            <div className="pointer-events-none absolute right-3 bottom-3 w-44 max-w-[34%] sm:w-56">
              <LocalPreview
                videoTrack={localVideoTrack ?? null}
                audioTrack={localAudioTrack ?? null}
                className="shadow-pop aspect-video w-full rounded-xl ring-2 ring-white"
              />
              {/* 어느 쪽이 내 화면인지 밝힌다. 레벨 미터(바닥 1.5)보다 한 칸 위에 둔다 */}
              <span className="absolute bottom-3 left-2 rounded-md bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur-md">
                나
              </span>
            </div>
          )}

          {/* 종료 실패 등 안내 — 무대 아래 가운데 */}
          {notice && (
            <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-4">
              <span
                role="alert"
                className="bg-surface-panel text-danger shadow-pop rounded-full px-4 py-2 text-[13px] font-medium"
              >
                {notice}
              </span>
            </div>
          )}
        </main>

        {/* 오른쪽 — 면접관 도구. 꼬리질문이 위, 자동 기록이 아래다.
            좁은 화면에서는 무대 아래로 내려 높이를 나눠 쓴다. */}
        {isInterviewer && (
          <aside className="flex max-h-[42vh] min-h-0 shrink-0 flex-col gap-3 lg:max-h-none lg:w-[360px] xl:w-[400px]">
            <SuggestionPanel />
            <TranscriptPanel />
          </aside>
        )}
      </div>
    </div>
  );
}
