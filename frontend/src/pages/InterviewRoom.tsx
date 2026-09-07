/**
 * 이랴(IRYA) — 면접 중 화면 (S2)
 *
 * 연결부. LiveKit 방 접속과 세션 종료를 담당하고, 그리기는 InterviewRoomView 에 맡긴다.
 *
 * 범위: 방 생성·접속 / 면접자·면접관 1:1 / 음성 녹화 / 화상통화 프레임워크 설정
 * 제외: S1 기업 컨텍스트, S3 면접 기록, S4 지원자 목록
 */

import { useRef, useState } from 'react';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import { useInterviewRoom } from '../hooks/useInterviewRoom';
import { usePermissionCheck } from '../hooks/usePermissionCheck';
import type { EndSessionResponse } from '../types/interview';

export interface InterviewRoomProps {
  interviewId: string;
  candidateName: string;
  /** 통화 종료 후 면접 기록(S3)으로 이동 */
  onEnded: (result: EndSessionResponse | null) => void;
}

export default function InterviewRoom({ interviewId, candidateName, onEnded }: InterviewRoomProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  // 권한 확인이 먼저다. 트랙이 준비되기 전에는 방에 접속하지 않는다.
  const { status, videoTrack, audioTrack, release } = usePermissionCheck();
  const { error, leave } = useInterviewRoom({
    interviewId,
    videoRef,
    audioRef,
    ready: status === 'granted',
    videoTrack,
    audioTrack,
    onTracksPublished: release,
  });
  const [ending, setEnding] = useState(false);

  // 권한 실패 전용 화면은 #5 범위다. 지금은 코드만 노출한다.
  const failure = status === 'granted' || status === 'requesting' ? null : `PERMISSION_${status}`;

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
      candidateName={candidateName}
      videoRef={videoRef}
      audioRef={audioRef}
      error={error ?? failure}
      ending={ending}
      onEnd={() => void handleEnd()}
      localVideoTrack={videoTrack}
      localAudioTrack={audioTrack}
    />
  );
}
