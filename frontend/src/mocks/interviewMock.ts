/**
 * 개발용 목 데이터.
 *
 * BE #9(방 생성·토큰) 와 AI #7(전사) 이 없어도 면접 화면을 눈으로 확인하기 위한 임시 코드다.
 * 실제 연결이 붙는 #5 · #8 에서 이 파일과 App.tsx 의 분기를 통째로 지운다.
 *
 * LiveKit 은 연결하지 않는다. 원격 영상 영역은 비어 있고,
 * 전사 · 추천 질문 · 화자 표시 · 경과 시간만 스토어를 통해 실제로 움직인다.
 */

import { ConnectionState } from 'livekit-client';
import { useInterviewStore } from '../stores/interviewStore';
import type { StreamEvent } from '../types/interview';

/** at(초) 시점에 흘려보낼 이벤트 */
type ScheduledEvent = { after: number; event: StreamEvent };

const SCRIPT: ScheduledEvent[] = [
  { after: 600, event: { type: 'speech.start', speaker: 'interviewer', at: 3 } },
  {
    after: 300,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u1',
      speaker: 'interviewer',
      text: '자기소개 부탁드립니다.',
      at: 3,
      final: true,
    },
  },
  { after: 900, event: { type: 'speech.end', speaker: 'interviewer', at: 6 } },

  { after: 500, event: { type: 'speech.start', speaker: 'candidate', at: 7 } },
  {
    after: 400,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u2',
      speaker: 'candidate',
      text: '네, 저는 3년차 백엔드 개발자입니다. ',
      at: 7,
      final: false,
    },
  },
  {
    after: 1100,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u2',
      speaker: 'candidate',
      text: '최근에는 실시간 스트리밍 파이프라인을 맡아 ',
      at: 7,
      final: false,
    },
  },
  {
    after: 1100,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u2',
      speaker: 'candidate',
      text: '초당 2만 건 처리까지 끌어올렸습니다.',
      at: 7,
      final: true,
    },
  },
  { after: 500, event: { type: 'speech.end', speaker: 'candidate', at: 21 } },

  // 추천 질문은 지원자 발화가 끝난 뒤에만 도착한다.
  {
    after: 700,
    event: {
      type: 'suggestion.created',
      id: 's1',
      text: '초당 2만 건은 어떤 병목을 해결해서 나온 수치인가요?',
      reason: '성능 수치를 언급했으나 근거가 없습니다',
      at: 22,
    },
  },
  {
    after: 1400,
    event: {
      type: 'suggestion.created',
      id: 's2',
      text: '그 파이프라인에서 직접 설계한 부분은 어디까지인가요?',
      reason: '팀 성과와 개인 기여가 구분되지 않았습니다',
      at: 24,
    },
  },

  { after: 1200, event: { type: 'speech.start', speaker: 'interviewer', at: 26 } },
  {
    after: 400,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u3',
      speaker: 'interviewer',
      text: '초당 2만 건은 어떤 병목을 해결해서 나온 수치인가요?',
      at: 26,
      final: true,
    },
  },
  { after: 1000, event: { type: 'speech.end', speaker: 'interviewer', at: 31 } },
];

/**
 * 목 세션을 시작한다. 정리 함수를 돌려주므로 이펙트에서 그대로 반환하면 된다.
 */
export function startMockSession(): () => void {
  const { setSession, setConnection, setCandidateJoined, applyStreamEvent, reset } =
    useInterviewStore.getState();

  setSession('mock-session');
  setConnection(ConnectionState.Connected);
  setCandidateJoined(true);

  const timers: ReturnType<typeof setTimeout>[] = [];
  let elapsed = 0;
  for (const { after, event } of SCRIPT) {
    elapsed += after;
    timers.push(setTimeout(() => applyStreamEvent(event), elapsed));
  }

  return () => {
    timers.forEach(clearTimeout);
    reset();
  };
}
