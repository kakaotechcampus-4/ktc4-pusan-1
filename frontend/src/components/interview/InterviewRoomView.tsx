/**
 * 면접 중 화면(S2)의 표현부.
 *
 * 상대 화면이 전체를 채우고 자기 화면은 PiP 로 얹는다.
 *
 * 역할에 따라 얹는 것이 다르다.
 *
 *   면접관  전사 · 추천 질문 · 면접 종료
 *   지원자  없음 · 나가기
 *
 * 지원자에게 추천 질문을 보이면 안 된다 — 면접관이 무엇을 물어볼지 미리 알게 된다.
 * 전사도 감춘다. 본인 발화가 실시간으로 받아적히는 것을 보면 답변이 위축된다.
 *
 * 연결(LiveKit·API)은 여기서 다루지 않는다 — pages/InterviewRoom 이 담당한다.
 * 덕분에 서버 없이도 이 화면만 따로 띄워 확인할 수 있다.
 */

import { ConnectionState, type LocalAudioTrack, type LocalVideoTrack } from 'livekit-client';
import { useEffect, useState, type RefObject } from 'react';
import { fmt } from '../../lib/format';
import type { Role } from '../../types/interview';
import { useInterviewStore } from '../../stores/interviewStore';
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
  localVideoTrack?: LocalVideoTrack | null;
  localAudioTrack?: LocalAudioTrack | null;
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

  useEffect(() => {
    if (connection !== ConnectionState.Connected) return;
    const t = setInterval(() => setElapsed((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [connection]);

  return (
    // S2는 헤더를 숨기고 화면 전체를 영상에 할당한다.
    <div className="relative h-screen w-screen overflow-hidden bg-[#0B0E14]">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        className="absolute inset-0 h-full w-full object-cover"
      />
      <audio ref={audioRef} autoPlay />

      {/* 상대 미참가 / 연결 중 / 실패 */}
      {(!remoteJoined || error) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[#0B0E14]">
          <p className="text-2xl font-semibold text-white">
            {error
              ? '통화에 연결할 수 없습니다'
              : connection === ConnectionState.Connected
                ? // 면접관은 지원자 이름을 알지만, 지원자는 면접관 이름을 모를 수 있다.
                  `${remoteName} 님을 기다리고 있습니다`
                : '연결 중'}
          </p>
          {error && <p className="font-mono text-sm text-white/45">{error}</p>}
        </div>
      )}

      {/* 자기 화면 — 대기 오버레이보다 뒤에 두어 그 위에 그려진다.
          상대를 기다리는 동안 자기 카메라·마이크를 점검하는 것이 목적이다.

          z-index 를 주지 않는다. 추천 질문 패널이 오른쪽에서 아래로 자라기 때문에
          질문이 3개 이상이면 이 영역과 겹치는데, 그때는 패널이 위로 와야 한다 —
          PiP 가 질문 카드의 버튼을 가리면 클릭이 막힌다.
          아래 상단 컨테이너가 뒤에 오므로 패널이 자연히 위에 그려진다.
          클릭을 가로채지 않도록 pointer-events 도 끈다. */}
      {(localVideoTrack || localAudioTrack) && (
        // 위치는 래퍼가 잡는다. LocalPreview 는 자기 루트에 relative 를 두므로
        // 여기서 absolute 를 같이 넘기면 두 position 유틸리티가 충돌한다.
        <div className="pointer-events-none absolute right-7 bottom-7 w-60 max-w-[28vw]">
          <LocalPreview
            videoTrack={localVideoTrack ?? null}
            audioTrack={localAudioTrack ?? null}
            className="aspect-video w-full rounded-xl shadow-[0_6px_24px_rgba(0,0,0,.45)] ring-1 ring-white/15"
          />
        </div>
      )}

      {/* 상단 — 이름, 경과 시간, 종료 */}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start gap-4 p-7">
        <div className="pointer-events-auto flex items-center gap-3.5">
          <span className="rounded-lg bg-black/55 px-3.5 py-2 font-mono text-[15px] text-white backdrop-blur-md">
            {fmt(elapsed)}
          </span>
          <span className="text-[19px] font-semibold whitespace-nowrap text-white [text-shadow:0_1px_12px_rgba(0,0,0,.6)]">
            {remoteName}
          </span>
          <SpeakerBadge />
        </div>

        <span className="flex-1" />

        <div className="pointer-events-auto flex flex-col items-end gap-4">
          {/* 면접관만 면접을 끝낼 수 있다. 지원자는 자기 연결만 끊는다 —
              지원자가 나가도 세션은 살아 있어야 재입장할 수 있다. */}
          <button
            onClick={onEnd}
            disabled={ending}
            title={isInterviewer ? '면접 종료' : '나가기'}
            aria-label={isInterviewer ? '면접 종료' : '나가기'}
            className={
              isInterviewer
                ? 'flex h-12 w-12 items-center justify-center rounded-full bg-[#D64545] text-xl text-white transition hover:bg-[#BC3838] disabled:opacity-50'
                : 'rounded-full bg-black/55 px-5 py-3 text-[15px] font-medium text-white backdrop-blur-md transition hover:bg-black/70 disabled:opacity-50'
            }
          >
            {isInterviewer ? '✕' : '나가기'}
          </button>
          {isInterviewer && <SuggestionPanel />}
        </div>
      </div>

      {/* 프로토타입 안내 — 전사 패널과 겹치지 않게 가운데 아래에 둔다 */}
      {notice && (
        <div className="pointer-events-none absolute inset-x-0 bottom-7 flex justify-center">
          <span className="rounded-full bg-black/60 px-4 py-2 text-[13px] text-white/70 backdrop-blur-md">
            {notice}
          </span>
        </div>
      )}

      {/* 하단 — 전사. 면접관 전용이다 */}
      {isInterviewer && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 p-7">
          <TranscriptPanel />
        </div>
      )}
    </div>
  );
}
