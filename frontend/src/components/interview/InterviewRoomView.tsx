/**
 * 면접 중 화면(S2)의 표현부.
 *
 * 상대 화면이 전체를 채우고, 그 위에 유리판(반투명 + blur) HUD 를 얹는다.
 * 시안(1. full screen video layout)의 구성을 따른다 —
 * 위에는 상대 정보와 종료, 아래는 왼쪽에 전사 · 오른쪽에 자기 화면이다.
 *
 * 역할에 따라 얹는 것이 다르다.
 *
 *   면접관  전사 · 면접 종료
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
import { LocalPreview } from './LocalPreview';
import { SpeakerBadge } from './SpeakerBadge';
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
    // S2는 헤더를 숨기고 화면 전체를 영상에 할당한다.
    <div className="bg-surface relative h-screen w-screen overflow-hidden">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        className="absolute inset-0 h-full w-full object-cover"
      />
      <audio ref={audioRef} autoPlay />

      {/* 비네트 — 영상이 밝아도 위아래 HUD 글자가 읽히도록 가장자리를 눌러둔다 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-black/45"
      />

      {/* 상대 미참가 / 연결 중 / 실패 */}
      {(!remoteJoined || error) && (
        <div className="bg-surface absolute inset-0 flex flex-col items-center justify-center gap-3">
          <span className="material-symbols-outlined text-ink-dim text-[40px]">
            {error ? 'wifi_off' : 'videocam'}
          </span>
          <p className="text-ink text-xl font-semibold">
            {error
              ? '통화에 연결할 수 없습니다'
              : connection === 'connected'
                ? // 면접관은 지원자 이름을 알지만, 지원자는 면접관 이름을 모를 수 있다.
                  `${remoteName} 님을 기다리고 있습니다`
                : '연결 중'}
          </p>
          {error && <p className="text-ink-dim font-mono text-sm">{error}</p>}
        </div>
      )}

      {/* 자기 화면 — 대기 오버레이보다 뒤에 두어 그 위에 그려진다.
          상대를 기다리는 동안 자기 카메라·마이크를 점검하는 것이 목적이다.

          클릭을 가로채지 않도록 pointer-events 를 끈다. */}
      {(localVideoTrack || localAudioTrack) && (
        // 위치는 래퍼가 잡는다. LocalPreview 는 자기 루트에 relative 를 두므로
        // 여기서 absolute 를 같이 넘기면 두 position 유틸리티가 충돌한다.
        <div className="pointer-events-none absolute right-4 bottom-4 w-56 max-w-[28vw]">
          <LocalPreview
            videoTrack={localVideoTrack ?? null}
            audioTrack={localAudioTrack ?? null}
            className="aspect-video w-full rounded-2xl shadow-[0_16px_36px_rgba(0,0,0,.45)] ring-1 ring-white/15"
          />
          {/* 어느 쪽이 내 화면인지 밝힌다. 레벨 미터(바닥 1.5)보다 한 칸 위에 둔다 */}
          <span className="text-ink absolute bottom-3 left-2 rounded-lg border border-white/10 bg-black/60 px-2 py-0.5 text-[11px] font-medium backdrop-blur-md">
            나
          </span>
        </div>
      )}

      {/* 상단 — 상대, 진행 상태, 종료. 시안의 유리 헤더 하나로 묶는다 */}
      <div className="pointer-events-none absolute inset-x-0 top-0 p-4">
        <header className="pointer-events-auto flex items-center gap-3 rounded-2xl border border-white/10 bg-black/45 px-4 py-2.5 backdrop-blur-xl">
          {/* 프로필 사진 자리. 우리에겐 사진이 없어 아이콘으로 자리만 지킨다 */}
          <span className="text-ink-muted flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-white/15 bg-white/10">
            <span className="material-symbols-outlined text-[20px]">person</span>
          </span>
          <span className="text-ink truncate text-[15px] font-semibold">{remoteName}</span>

          <div className="flex shrink-0 items-center gap-2.5 border-l border-white/15 pl-3">
            {live && (
              <span className="text-ink-muted inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/40 px-2.5 py-1 text-[11px] font-medium">
                <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
                LIVE
              </span>
            )}
            <span className="text-ink font-mono text-[15px] font-bold tracking-wider">
              {fmt(elapsed)}
            </span>
          </div>

          <SpeakerBadge />

          <span className="flex-1" />

          {/* 면접관만 면접을 끝낼 수 있다. 지원자는 자기 연결만 끊는다 —
              지원자가 나가도 세션은 살아 있어야 재입장할 수 있다. */}
          <button
            onClick={onEnd}
            disabled={ending}
            title={isInterviewer ? '면접 종료' : '나가기'}
            aria-label={isInterviewer ? '면접 종료' : '나가기'}
            className={`flex shrink-0 items-center gap-1.5 rounded-full px-4 py-1.5 text-[13px] font-semibold transition disabled:opacity-50 ${
              isInterviewer
                ? 'bg-red-500 text-white hover:bg-red-600'
                : 'text-ink border border-white/10 bg-white/10 hover:bg-white/20'
            }`}
          >
            <span className="material-symbols-outlined text-[18px]">
              {isInterviewer ? 'call_end' : 'logout'}
            </span>
            {isInterviewer ? '면접 종료' : '나가기'}
          </button>
        </header>
      </div>

      {/* 프로토타입 안내 — 전사 패널과 자기 화면 사이, 가운데 아래에 둔다 */}
      {notice && (
        <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center">
          <span className="text-ink-muted rounded-full border border-white/10 bg-black/60 px-4 py-2 text-[13px] backdrop-blur-md">
            {notice}
          </span>
        </div>
      )}

      {/* 하단 왼쪽 — 전사. 면접관 전용이다 */}
      {isInterviewer && (
        <div className="pointer-events-none absolute bottom-4 left-4">
          <TranscriptPanel />
        </div>
      )}
    </div>
  );
}
