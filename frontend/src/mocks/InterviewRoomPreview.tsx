/**
 * 서버 없이 면접 화면을 확인하는 미리보기.
 *
 * LiveKit 도 API 도 붙이지 않고 스토어에만 목 이벤트를 흘린다.
 * 원격 영상 영역은 비어 있는 것이 정상이다 — 실제 트랙은 #5 에서 붙는다.
 *
 * #5 · #8 착수 시 mocks/ 디렉터리와 App.tsx 의 분기를 함께 지운다.
 */

import { useEffect, useRef } from 'react';
import { InterviewRoomView } from '../components/interview/InterviewRoomView';
import { startMockSession } from './interviewMock';

export function InterviewRoomPreview() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => startMockSession(), []);

  return (
    <InterviewRoomView
      candidateName="김지원"
      videoRef={videoRef}
      audioRef={audioRef}
      error={null}
      ending={false}
      onEnd={() => {}}
    />
  );
}
