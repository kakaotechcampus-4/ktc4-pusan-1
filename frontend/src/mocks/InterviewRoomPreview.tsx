/**
 * 서버 없이 면접 화면을 확인하는 미리보기.
 *
 * LiveKit 은 붙이지 않고 스토어에만 목 이벤트를 흘린다.
 * 다만 세션 상태 API(start·end)는 **실제로 호출한다** — 목 서버가 받는다.
 * 자기 화면(PiP)은 **실제 카메라 트랙**이다 — 기기 점검에서 얻은 것을 그대로 받는다.
 *
 * 상대 영상 자리에도 같은 트랙을 붙인다. LiveKit 서버가 없어 원격 참가자가 존재하지
 * 않는데, 그대로 두면 화면이 검게 남아 고장난 것처럼 보인다.
 * 대신 화면에 무엇이 대체된 것인지 문구로 밝힌다 — 시연에서 오해가 없어야 한다.
 *
 * ⚠️ BE·AI 연동 시 mocks/ 디렉터리와 App.tsx 의 분기를 함께 지운다.
 */

import type { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';
import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { endSession, startSession } from '../api/interview';
import { FALLBACK_CANDIDATE, INTERVIEWER_LABEL } from '../lib/candidateName';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import type { Role } from '../types/interview';
import { startMockSession } from './interviewMock';

export interface InterviewRoomPreviewProps {
  /** 지정하면 URL 파라미터보다 우선한다 */
  role?: Role;
  /** 있으면 상태 전이 API 를 실제로 호출한다 */
  sessionId?: string;
  /** 상대 이름. 없으면 역할에 맞는 기본값을 쓴다 */
  remoteName?: string;
  /** 기기 점검에서 확보한 실제 트랙. 없으면 PiP 를 그리지 않는다 */
  localVideoTrack?: LocalVideoTrack | null;
  localAudioTrack?: LocalAudioTrack | null;
  onLeave?: () => void;
}

export function InterviewRoomPreview({
  role: roleProp,
  sessionId,
  remoteName,
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

  useEffect(() => startMockSession(), []);

  /* 상대 영상 자리를 내 카메라로 채운다.
     하나의 트랙은 여러 요소에 attach 할 수 있어 PiP 와 동시에 쓸 수 있다.
     detach 는 이 요소만 떼어 PiP 에는 영향을 주지 않는다. */
  useEffect(() => {
    const el = videoRef.current;
    if (!localVideoTrack || !el) return;
    localVideoTrack.attach(el);
    return () => {
      localVideoTrack.detach(el);
    };
  }, [localVideoTrack]);

  const start = useMutation({ mutationFn: (id: string) => startSession(id) });

  // 면접 진행 상태로 전이시킨다. 명세상 면접관만 호출한다.
  // 여러 번 호출돼도 서버가 한 번만 전이시켜야 한다 (issue #9 완료 조건).
  //
  // start 를 deps 에 넣지 않는다. 뮤테이션 객체는 렌더마다 새로 만들어져
  // 넣으면 매 렌더마다 다시 호출된다.
  useEffect(() => {
    if (!sessionId || roleResolved !== 'INTERVIEWER') return;
    start.mutate(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, roleResolved]);

  // 면접관만 세션을 끝낸다. 지원자는 자기 연결만 끊는다 —
  // 참가자 disconnect 와 면접 종료는 별개다 (명세 07).
  // 종료 요청이 실패해도 화면은 나간다. 통화에서 빠지는 것이 우선이다.
  const end = useMutation({
    mutationFn: (id: string) => endSession(id),
    onSettled: () => onLeave?.(),
  });

  const ending = end.isPending;

  const handleEnd = () => {
    if (sessionId && roleResolved === 'INTERVIEWER') {
      end.mutate(sessionId);
      return;
    }
    onLeave?.();
  };

  return (
    <InterviewRoomView
      role={roleResolved}
      remoteName={
        remoteName ?? (roleResolved === 'INTERVIEWER' ? FALLBACK_CANDIDATE : INTERVIEWER_LABEL)
      }
      videoRef={videoRef}
      audioRef={audioRef}
      error={null}
      ending={ending}
      onEnd={handleEnd}
      localVideoTrack={localVideoTrack}
      localAudioTrack={localAudioTrack}
      notice={
        localVideoTrack
          ? '프로토타입 — 상대 영상 자리에 내 카메라를 대신 표시합니다'
          : '프로토타입 — 전사와 추천 질문은 목 데이터입니다'
      }
    />
  );
}
