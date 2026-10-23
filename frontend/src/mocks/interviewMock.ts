/**
 * 개발용 목 데이터.
 *
 * BE #9(방 생성·토큰) 와 AI #7(전사) 이 없어도 면접 화면을 눈으로 확인하기 위한 임시 코드다.
 * 실제 연결이 붙는 #5 · #8 에서 이 파일과 App.tsx 의 분기를 통째로 지운다.
 *
 * LiveKit 은 연결하지 않는다. 원격 영상 영역은 비어 있고,
 * 전사 · 꼬리질문 · 화자 표시 · 경과 시간만 스토어를 통해 실제로 움직인다.
 *
 * 꼬리질문은 두 통로를 모두 흉내낸다 — 쌓여 있던 것은 조회 API(목 서버가 받는다)로
 * 한 번 불러오고, 그 뒤에 오는 것은 대본이 스토어에 직접 넣는다. 실제로는 LiveKit
 * 데이터 패킷으로 오는데 여기서는 방에 붙지 않기 때문이다.
 */

import { listSuggestions } from '../api/suggestions';
import { useInterviewStore } from '../stores/interviewStore';
import type { StreamEvent } from '../types/interview';

/** at(초) 시점에 흘려보낼 이벤트 */
type ScheduledEvent = { after: number; event: StreamEvent };

const SCRIPT: ScheduledEvent[] = [
  { after: 600, event: { type: 'speech.start', speaker: 'INTERVIEWER', at: 3 } },
  {
    after: 300,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u1',
      speaker: 'INTERVIEWER',
      text: '자기소개 부탁드립니다.',
      at: 3,
      final: true,
    },
  },
  { after: 900, event: { type: 'speech.end', speaker: 'INTERVIEWER', at: 6 } },

  { after: 500, event: { type: 'speech.start', speaker: 'CANDIDATE', at: 7 } },
  {
    after: 400,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u2',
      speaker: 'CANDIDATE',
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
      speaker: 'CANDIDATE',
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
      speaker: 'CANDIDATE',
      text: '초당 2만 건 처리까지 끌어올렸습니다.',
      at: 7,
      final: true,
    },
  },
  { after: 500, event: { type: 'speech.end', speaker: 'CANDIDATE', at: 21 } },

  { after: 1200, event: { type: 'speech.start', speaker: 'INTERVIEWER', at: 26 } },
  {
    after: 400,
    event: {
      type: 'transcript.delta',
      utteranceId: 'u3',
      speaker: 'INTERVIEWER',
      text: '초당 2만 건은 어떤 병목을 해결해서 나온 수치인가요?',
      at: 26,
      final: true,
    },
  },
  { after: 1000, event: { type: 'speech.end', speaker: 'INTERVIEWER', at: 31 } },
];

/** 면접 중에 도착하는 꼬리질문. 시각은 목 세션 시작 기준(ms)이다 */
const SUGGESTIONS: { at: number; id: string; content: string }[] = [
  // 지원자가 수치를 말한 직후다. 면접관이 이걸 보고 다음 질문을 던지는 흐름이 보이게 둔다.
  { at: 7400, id: 'sug_mock_1', content: '초당 2만 건은 어떤 병목을 해결해서 나온 수치인가요?' },
  { at: 8200, id: 'sug_mock_2', content: '그 파이프라인에서 직접 설계한 부분은 어디인가요?' },
  // 면접관이 이미 다음 질문을 하고 있는 중에 들어온다. 고정해 둔 것이 밀리지 않는지 본다.
  {
    at: 11500,
    id: 'sug_mock_3',
    content: '장애가 났을 때 복구는 어떻게 하셨는지 들어볼 수 있을까요?',
  },
];

/**
 * 목 세션을 시작한다. 정리 함수를 돌려주므로 이펙트에서 그대로 반환하면 된다.
 */
export function startMockSession(): () => void {
  const {
    setSession,
    setConnection,
    setRemoteJoined,
    applyStreamEvent,
    addSuggestion,
    mergeSuggestions,
    reset,
  } = useInterviewStore.getState();

  setSession('mock-session');
  setConnection('connected');

  const timers: ReturnType<typeof setTimeout>[] = [];
  let cancelled = false;

  // 입장 직후 조회. 실제 화면도 같은 함수를 부른다 — 목으로 그 경로까지 확인한다.
  void listSuggestions('mock-session')
    .then((list) => {
      if (!cancelled) mergeSuggestions(list);
    })
    .catch((e: unknown) => console.warn('목 꼬리질문 조회 실패', e));

  // 상대가 곧바로 들어와 있으면 대기 화면을 볼 수 없다.
  // 잠깐 대기 상태를 보여준 뒤 입장시켜, 실제 흐름과 같은 순서로 확인되게 한다.
  timers.push(setTimeout(() => setRemoteJoined(true), 1800));

  // 대본은 상대가 들어온 뒤부터 흐른다.
  let elapsed = 1800;
  for (const { after, event } of SCRIPT) {
    elapsed += after;
    timers.push(setTimeout(() => applyStreamEvent(event), elapsed));
  }

  for (const { at, id, content } of SUGGESTIONS) {
    timers.push(
      setTimeout(
        () => addSuggestion({ id, content, createdAt: new Date().toISOString(), pinned: false }),
        at,
      ),
    );
  }

  return () => {
    cancelled = true;
    timers.forEach(clearTimeout);
    reset();
  };
}
