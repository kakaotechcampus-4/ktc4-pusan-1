/**
 * 면접 중 화면(S2)의 표현부.
 *
 * 상대 영상이 화면 전체를 채우고, 상태 막대 · 꼬리질문 · 자동 기록 · 내 화면이 그 위에
 * 거의 투명한 유리판으로 뜬다 (#236, `index.css` 의 `.glass`). 마우스를 올리면 또렷해진다.
 *
 * 역할에 따라 얹는 것이 다르다.
 *
 *   면접관  전사 · 꼬리질문 · 메모 · 면접 종료
 *   지원자  없음 · 나가기
 *
 * 지원자에게는 전사를 감춘다. 본인 발화가 실시간으로 받아적히는 것을 보면 답변이 위축된다.
 *
 * 연결(LiveKit·API)은 여기서 다루지 않는다 — pages/InterviewRoom 이 담당한다.
 * 덕분에 서버 없이도 이 화면만 따로 띄워 확인할 수 있다.
 */

import { ConnectionState } from 'livekit-client';
import { useEffect, useState, type MouseEvent, type RefObject } from 'react';
import { fmt } from '../../lib/format';
import type { Role } from '../../types/interview';
import { useInterviewStore } from '../../stores/interviewStore';
import { Logo } from '../ui/Logo';
import { LocalPreview } from './LocalPreview';
import { MemoPanel } from './MemoPanel';
import { SpeakerBadge } from './SpeakerBadge';
import { SuggestionPanel } from './SuggestionPanel';
import { TranscriptPanel } from './TranscriptPanel';

export interface InterviewRoomViewProps {
  /** 내 역할. 화면에 무엇을 얹을지 결정한다 */
  role: Role;
  /** 메모 초안을 이 탭에 남겨 두는 자리를 가른다 */
  sessionId: string;
  /** 메모를 저장할 면접. 방에 붙어 상태를 조회한 뒤에 온다 */
  interviewId: string | null;
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
  sessionId,
  interviewId,
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

  // 영상이나 빈 자리를 눌러도 메모에서 커서가 빠지지 않게 한다 (#219). 누를 것이 없는
  // 자리라 포커스가 넘어가도 얻는 것이 없고, 넘어가면 이어서 친 글자가 아무 데도 안 간다.
  // 패널 안쪽은 막지 않는다 — 자막을 긁어 복사하는 것까지 막을 이유는 없다.
  const keepCaret = (e: MouseEvent) => {
    if (e.target === e.currentTarget) e.preventDefault();
  };

  return (
    // 상대 영상이 화면 전체를 채우고, 상태 막대 · 꼬리질문 · 메모 · 자동 기록 · 내 화면은
    // 그 위에 유리판으로 뜬다 (#236). 유리판은 평소 거의 투명하고 마우스를 올리면 또렷해진다.
    <div
      onMouseDown={keepCaret}
      className="relative h-screen w-screen overflow-hidden bg-[radial-gradient(120%_90%_at_20%_0%,#2b2f7a_0%,#141836_45%,#0b0e1c_100%)] text-white"
    >
      <video
        ref={videoRef}
        autoPlay
        playsInline
        onMouseDown={keepCaret}
        className="absolute inset-0 h-full w-full object-cover"
      />
      <audio ref={audioRef} autoPlay />

      {/* 영상이 밝아도 위아래 유리판 글자가 읽히도록 가장자리를 살짝 누른다 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/35 via-transparent to-black/45"
      />

      {/* 상대 미참가 / 연결 중 / 실패 — 무대 가운데 유리판 하나 */}
      {(!remoteJoined || error) && (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          {/* 물방울처럼 번지는 빛. 정보는 없다 */}
          <div
            aria-hidden
            className="bg-brand/30 absolute top-1/3 left-1/3 h-72 w-72 rounded-full blur-3xl"
          />
          <div
            aria-hidden
            className="bg-accent/20 absolute right-1/4 bottom-1/4 h-60 w-60 rounded-full blur-3xl"
          />
          <div className="glass relative flex max-w-md flex-col items-center gap-3 rounded-3xl px-8 py-7 text-center">
            {error ? (
              <span className="bg-danger-tint text-danger flex h-12 w-12 items-center justify-center rounded-full">
                <span aria-hidden className="material-symbols-outlined text-[26px]">
                  wifi_off
                </span>
              </span>
            ) : (
              <span
                aria-hidden
                className="h-9 w-9 animate-spin rounded-full border-[3px] border-white/25 border-t-white"
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
                  입장하면 이 자리에 화면이 나타납니다. 그동안 내 화면을 확인해주세요.
                </p>
              )
            )}
          </div>
        </div>
      )}

      {/* 위 — 상대, 진행 상태, 종료 */}
      <header className="glass absolute inset-x-3 top-3 z-10 flex items-center gap-3 rounded-2xl px-3 py-2 sm:inset-x-4 sm:top-4 sm:px-4">
        <div className="glass-dim flex min-w-0 flex-1 items-center gap-3">
          {/* 좁은 화면에서는 상대 이름 · 시간이 먼저라 로고를 뺀다 */}
          <span className="hidden sm:block">
            <Logo size="sm" />
          </span>
          <span aria-hidden className="bg-border-base hidden h-6 w-px sm:block" />
          {/* 프로필 사진 자리. 우리에겐 사진이 없어 이름 첫 글자로 자리를 지킨다 */}
          <span className="bg-surface-bright flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-bold">
            {remoteName.slice(0, 1)}
          </span>
          <span className="min-w-0 truncate text-[15px] font-semibold">{remoteName}</span>
          <span className="font-mono text-[15px] font-bold tracking-wider tabular-nums">
            {fmt(elapsed)}
          </span>
          <span className="hidden md:block">
            <SpeakerBadge />
          </span>
        </div>

        {/* 진행 중 표시는 흐리지 않는다 — 녹화 · 통화 중인지는 늘 보여야 한다 */}
        {live && (
          <span className="bg-danger-tint text-danger inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold">
            <span className="h-2 w-2 animate-pulse rounded-full bg-[#ff5a63]" />
            LIVE
          </span>
        )}

        {/* 면접관만 면접을 끝낼 수 있다. 지원자는 자기 연결만 끊는다 —
            지원자가 나가도 세션은 살아 있어야 재입장할 수 있다. */}
        <button
          type="button"
          onClick={onEnd}
          disabled={ending}
          title={isInterviewer ? '면접 종료' : '나가기'}
          aria-label={isInterviewer ? '면접 종료' : '나가기'}
          className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold text-white transition disabled:opacity-50 sm:px-4 ${
            isInterviewer ? 'bg-[#e5484d]/90 hover:bg-[#e5484d]' : 'bg-white/15 hover:bg-white/25'
          }`}
          style={{ textShadow: 'none' }}
        >
          <span aria-hidden className="material-symbols-outlined text-[18px]">
            {isInterviewer ? 'call_end' : 'logout'}
          </span>
          <span className="hidden sm:inline">{isInterviewer ? '면접 종료' : '나가기'}</span>
        </button>
      </header>

      {/* 상대 이름표 — 영상이 보일 때만 */}
      {remoteJoined && !error && (
        <span className="glass absolute top-[72px] left-3 rounded-full px-3 py-1 text-[13px] font-medium sm:top-[80px] sm:left-4">
          {remoteName}
        </span>
      )}

      {/* 오른쪽 — AI 꼬리질문과 메모. 면접관 전용이다.
          메모를 꼬리질문 바로 아래에 둔다 — 질문을 고정하고 받아적는 일이 한 자리에서
          끝나야 면접 중에 눈과 마우스가 화면을 왕복하지 않는다.
          아래는 내 화면(오른쪽 아래)이 쓰는 자리라 비워 둔다. */}
      {isInterviewer && (
        <div className="absolute top-[72px] right-3 bottom-[19.5rem] flex w-[min(380px,calc(100%-24px))] flex-col gap-2 sm:top-[80px] sm:right-4 sm:bottom-[11rem]">
          <div className="flex max-h-[38vh] shrink-0">
            <SuggestionPanel />
          </div>
          <MemoPanel sessionId={sessionId} interviewId={interviewId} />
        </div>
      )}

      {/* 왼쪽 아래 — 실시간 자막. 면접관 전용이다 */}
      {isInterviewer && (
        <div className="absolute inset-x-3 bottom-3 sm:inset-x-auto sm:bottom-4 sm:left-4 sm:w-[min(560px,calc(100%-19rem))]">
          <TranscriptPanel />
        </div>
      )}

      {/* 오른쪽 아래 — 내 화면. 대기 화면 위에 그려져 기다리는 동안 카메라를 볼 수 있다.
          클릭을 가로채지 않도록 pointer-events 를 끈다. 좁은 화면의 면접관은 자막이
          바닥을 쓰므로 그 위로 올린다. */}
      {(localVideoTrack || localAudioTrack) && (
        // 위치는 래퍼가 잡는다. LocalPreview 는 자기 루트에 relative 를 두므로
        // 여기서 absolute 를 같이 넘기면 두 position 유틸리티가 충돌한다.
        <div
          className={`pointer-events-none absolute right-3 w-36 sm:right-4 sm:bottom-4 sm:w-60 ${
            isInterviewer ? 'bottom-[13.5rem]' : 'bottom-3'
          }`}
        >
          <LocalPreview
            videoTrack={localVideoTrack ?? null}
            audioTrack={localAudioTrack ?? null}
            className="aspect-video w-full rounded-2xl shadow-[0_12px_32px_rgba(6,8,20,.35)] ring-1 ring-white/40"
          />
          <span className="glass absolute bottom-3 left-2 rounded-md px-2 py-0.5 text-[11px] font-medium">
            나
          </span>
        </div>
      )}

      {/* 종료 실패 등 안내 — 가운데 아래 */}
      {notice && (
        <div className="pointer-events-none absolute inset-x-0 bottom-24 flex justify-center px-4">
          <span
            role="alert"
            className="glass text-danger rounded-full px-4 py-2 text-[13px] font-medium"
          >
            {notice}
          </span>
        </div>
      )}
    </div>
  );
}
