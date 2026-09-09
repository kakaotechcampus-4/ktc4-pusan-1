/**
 * 서버 없이 면접 화면을 확인하는 미리보기.
 *
 * LiveKit 은 붙이지 않고 스토어에만 목 이벤트를 흘린다.
 * 다만 세션 상태 API(start·end)는 **실제로 호출한다** — 목 서버가 받는다.
 * 다만 자기 화면(PiP)은 **실제 카메라 트랙**이다 — 기기 점검에서 얻은 것을 그대로 받는다.
 * 원격 영상 영역은 비어 있는 것이 정상이다.
 *
 * ⚠️ BE·AI 연동 시 mocks/ 디렉터리와 App.tsx 의 분기를 함께 지운다.
 */

import type { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { endSession, startSession } from '../api/interview';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import type { Role } from '../types/interview';
import { startMockSession } from './interviewMock';

export interface InterviewRoomPreviewProps {
  /** 지정하면 URL 파라미터보다 우선한다 */
  role?: Role;
  /** 있으면 상태 전이 API 를 실제로 호출한다 */
  sessionId?: string;
  /** 기기 점검에서 확보한 실제 트랙. 없으면 PiP 를 그리지 않는다 */
  localVideoTrack?: LocalVideoTrack | null;
  localAudioTrack?: LocalAudioTrack | null;
  onLeave?: () => void;
}

export function InterviewRoomPreview({
  role: roleProp,
  sessionId,
  localVideoTrack,
  localAudioTrack,
  onLeave,
}: InterviewRoomPreviewProps = {}) {
  // ?role=candidate 로 지원자 화면을 확인한다. 기본은 면접관이다.
  const [searchParams] = useSearchParams();
  const roleResolved: Role =
    roleProp ?? (searchParams.get('role') === 'candidate' ? 'CANDIDATE' : 'INTERVIEWER');

  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [ending, setEnding] = useState(false);

  useEffect(() => startMockSession(), []);

  // 면접 진행 상태로 전이시킨다. 명세상 면접관만 호출한다.
  // 여러 번 호출돼도 서버가 한 번만 전이시켜야 한다 (issue #9 완료 조건).
  useEffect(() => {
    if (!sessionId || roleResolved !== 'INTERVIEWER') return;
    void startSession(sessionId).catch((e: unknown) => console.warn('면접 시작 실패', e));
  }, [sessionId, roleResolved]);

  const handleEnd = async () => {
    setEnding(true);
    try {
      // 면접관만 세션을 끝낸다. 지원자는 자기 연결만 끊는다 —
      // 참가자 disconnect 와 면접 종료는 별개다 (명세 07).
      if (sessionId && roleResolved === 'INTERVIEWER') {
        await endSession(sessionId);
      }
      onLeave?.();
    } catch (e) {
      console.warn('면접 종료 실패', e);
    } finally {
      setEnding(false);
    }
  };

  return (
    <InterviewRoomView
      role={roleResolved}
      remoteName={roleResolved === 'INTERVIEWER' ? '김지원' : '이면접'}
      videoRef={videoRef}
      audioRef={audioRef}
      error={null}
      ending={ending}
      onEnd={() => void handleEnd()}
      localVideoTrack={localVideoTrack}
      localAudioTrack={localAudioTrack}
    />
  );
}
