/**
 * 이랴(IRYA) — 면접 중 화면 (S2)
 *
 * 연결부. LiveKit 방 접속과 세션 종료를 담당하고, 그리기는 InterviewRoomView 에 맡긴다.
 *
 * 범위: 방 생성·접속 / 면접자·면접관 1:1 / 음성 녹화 / 화상통화 프레임워크 설정
 * 제외: S1 기업 컨텍스트, S3 면접 기록, S4 지원자 목록
 */

import type { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';
import { useRef, useState } from 'react';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import { useInterviewRoom } from '../hooks/useInterviewRoom';
import type { EndSessionResponse, Role } from '../types/interview';

export interface InterviewRoomProps {
  sessionId: string;
  role: Role;
  remoteName: string;
  /**
   * 기기 점검에서 확보한 트랙.
   *
   * 이 컴포넌트는 카메라·마이크를 직접 요청하지 않는다. 획득과 정리는 App.tsx 의
   * DeviceGate 한 곳에서만 한다 — 두 곳에서 가져오면 트랙이 둘로 갈라지고,
   * 한쪽을 stop 해도 다른 쪽이 살아 있어 카메라 표시등이 꺼지지 않는다.
   * LocalPreview 에도 같은 이유로 훅을 부르지 말라는 주석이 달려 있다.
   */
  videoTrack: LocalVideoTrack | null;
  audioTrack: LocalAudioTrack | null;
  /** 통화 종료 후 면접 기록(S3)으로 이동 */
  onEnded: (result: EndSessionResponse | null) => void;
}

export default function InterviewRoom({
  sessionId,
  role,
  remoteName,
  videoTrack,
  audioTrack,
  onEnded,
}: InterviewRoomProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const { error, leave } = useInterviewRoom({
    sessionId,
    role,
    videoRef,
    audioRef,
    // DeviceGate 를 통과한 뒤에만 그려지므로 사실상 항상 참이다. 그래도 트랙에서
    // 끌어낸다 — 트랙 없이 접속하면 아무것도 발행하지 못한 채 정원 한 자리를 차지한다.
    ready: videoTrack !== null || audioTrack !== null,
    videoTrack,
    audioTrack,
  });
  const [ending, setEnding] = useState(false);

  const handleEnd = async () => {
    setEnding(true);
    try {
      onEnded(await leave());
    } finally {
      setEnding(false);
    }
  };

  return (
    <InterviewRoomView
      role={role}
      remoteName={remoteName}
      videoRef={videoRef}
      audioRef={audioRef}
      error={error}
      ending={ending}
      onEnd={() => void handleEnd()}
      localVideoTrack={videoTrack}
      localAudioTrack={audioTrack}
    />
  );
}
