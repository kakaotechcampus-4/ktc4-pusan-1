/**
 * 서버 없이 면접 화면을 확인하는 미리보기.
 *
 * API 는 붙이지 않고 스토어에 목 이벤트만 흘린다.
 * 다만 면접관 자기 화면(PiP)은 실제 카메라·마이크 트랙을 쓴다 —
 * #8 의 로컬 프리뷰와 권한 처리를 BE 없이 확인할 유일한 진입점이기 때문이다.
 *
 * 지원자 영상 영역이 비어 있는 것은 정상이다 — 원격 트랙은 #5 에서 붙는다.
 *
 * #5 착수 시 mocks/ 디렉터리와 App.tsx 의 분기를 함께 지운다.
 */

import { useEffect, useRef } from 'react';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import { usePermissionCheck } from '../hooks/usePermissionCheck';
import { startMockSession } from './interviewMock';

export function InterviewRoomPreview() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // release() 는 부르지 않는다 — Room 이 없어 소유권을 넘길 대상이 없다.
  // 트랙은 훅이 계속 소유하고 언마운트 때 stop 된다.
  const { status, videoTrack, audioTrack } = usePermissionCheck();

  useEffect(() => startMockSession(), []);

  return (
    <InterviewRoomView
      candidateName="김지원"
      videoRef={videoRef}
      audioRef={audioRef}
      error={status === 'granted' || status === 'requesting' ? null : `PERMISSION_${status}`}
      ending={false}
      onEnd={() => {}}
      localVideoTrack={videoTrack}
      localAudioTrack={audioTrack}
    />
  );
}
