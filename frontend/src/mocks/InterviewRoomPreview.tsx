/**
 * 서버 없이 면접 화면을 확인하는 미리보기.
 *
 * LiveKit 도 API 도 붙이지 않고 스토어에만 목 이벤트를 흘린다.
 * 다만 자기 화면(PiP)은 **실제 카메라 트랙**이다 — 기기 점검에서 얻은 것을 그대로 받는다.
 * 원격 영상 영역은 비어 있는 것이 정상이다.
 *
 * ⚠️ BE·AI 연동 시 mocks/ 디렉터리와 App.tsx 의 분기를 함께 지운다.
 */

import type { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';
import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import type { Role } from '../types/interview';
import { startMockSession } from './interviewMock';

export interface InterviewRoomPreviewProps {
  /** 지정하면 URL 파라미터보다 우선한다 */
  role?: Role;
  /** 기기 점검에서 확보한 실제 트랙. 없으면 PiP 를 그리지 않는다 */
  localVideoTrack?: LocalVideoTrack | null;
  localAudioTrack?: LocalAudioTrack | null;
  onLeave?: () => void;
}

export function InterviewRoomPreview({
  role: roleProp,
  localVideoTrack,
  localAudioTrack,
  onLeave,
}: InterviewRoomPreviewProps = {}) {
  // ?role=candidate 로 지원자 화면을 확인한다. 기본은 면접관이다.
  const [searchParams] = useSearchParams();
  const role: Role =
    roleProp ?? (searchParams.get('role') === 'candidate' ? 'CANDIDATE' : 'INTERVIEWER');

  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => startMockSession(), []);

  return (
    <InterviewRoomView
      role={role}
      remoteName={role === 'INTERVIEWER' ? '김지원' : '이면접'}
      videoRef={videoRef}
      audioRef={audioRef}
      error={null}
      ending={false}
      onEnd={() => onLeave?.()}
      localVideoTrack={localVideoTrack}
      localAudioTrack={localAudioTrack}
    />
  );
}
