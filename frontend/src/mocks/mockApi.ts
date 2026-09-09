/**
 * 서버 없이 화면 흐름을 확인하기 위한 목 API.
 *
 * 프로토타입 단계에서 BE 가 아직 구현되지 않아, 링크 → 입장 → 기기 점검 → 면접 화면을
 * 끊김 없이 보여주기 위한 임시 코드다.
 *
 * 응답 형태는 docs/api 명세를 그대로 따른다 — 실제 서버가 붙으면
 * VITE_USE_MOCK_API 를 끄기만 하면 되고 화면 코드는 그대로다.
 *
 * ⚠️ BE 연동 시 이 파일과 api/client.ts 의 분기를 함께 지운다.
 */

import type {
  CreateSessionResponse,
  Interview,
  JoinSessionResponse,
  SessionState,
  StartSessionResponse,
} from '../types/interview';

/** 목이 켜져 있는가. 개발 모드에서만, 명시적으로 끄지 않은 경우에 동작한다. */
export const USE_MOCK_API = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_API !== 'false';

/** 실제 서버처럼 보이도록 약간의 지연을 준다. 로딩 상태가 화면에 드러나야 한다. */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 경로 → 응답. 실제 라우팅과 같은 모양으로 맞춰 둔다.
 * 매칭되지 않으면 null 을 돌려주고 호출부가 실제 fetch 로 넘어간다.
 */
let seq = 0;
const nextId = (prefix: string) => `${prefix}_${(++seq).toString().padStart(3, '0')}`;

/** 생성한 면접을 기억해 둔다. 조회가 같은 값을 돌려주게 하기 위해서다. */
const interviews = new Map<string, Interview>();

export async function handleMock(path: string, init?: RequestInit): Promise<unknown | null> {
  const method = init?.method ?? 'GET';

  if (path === '/api/v1/interviews' && method === 'POST') {
    await delay(400);
    const body = JSON.parse(String(init?.body ?? '{}')) as { interviewerId?: string };
    const interview: Interview = {
      interviewId: nextId('int'),
      interviewerId: body.interviewerId ?? 'user_mock',
      createdAt: new Date().toISOString(),
    };
    interviews.set(interview.interviewId, interview);
    return interview;
  }

  const getInterview = /^\/api\/v1\/interviews\/([^/]+)$/.exec(path);
  if (getInterview && method === 'GET') {
    await delay(200);
    return interviews.get(getInterview[1]) ?? null;
  }

  const createSession = /^\/api\/v1\/interviews\/([^/]+)\/sessions$/.exec(path);
  if (createSession && method === 'POST') {
    await delay(500);
    const sessionId = nextId('ses');
    return {
      sessionId,
      interviewId: createSession[1],
      status: 'WAITING',
      // 명세 예시는 https://irya.com/... 이지만, 목에서는 현재 오리진으로 만든다.
      // 그래야 복사한 링크를 다른 탭에서 실제로 열어볼 수 있다.
      // 실제 서버는 환경별 프론트 도메인을 주입해야 한다.
      inviteUrl: `${window.location.origin}/interview/${sessionId}`,
      createdAt: new Date().toISOString(),
    } satisfies CreateSessionResponse;
  }

  const start = /^\/api\/v1\/sessions\/([^/]+)\/start$/.exec(path);
  if (start && method === 'POST') {
    await delay(300);
    return {
      sessionId: start[1],
      status: 'INTERVIEWING',
      startedAt: new Date().toISOString(),
    } satisfies StartSessionResponse;
  }

  const join = /^\/api\/v1\/sessions\/([^/]+)\/join$/.exec(path);
  if (join && method === 'POST') {
    await delay(500);
    const sessionId = join[1];

    // 데모용 실패 경로 — 링크에 이 값을 넣으면 에러 화면을 보여줄 수 있다.
    if (sessionId === 'not-found') throw { status: 404 };
    if (sessionId === 'ended') throw { status: 409 };

    return {
      sessionId,
      // 실제 접속은 하지 않는다. useInterviewRoom 이 이 URL 로 connect 를 시도하면
      // 실패하므로, 프로토타입에서는 면접 화면이 목 이벤트로만 동작한다.
      livekitUrl: 'wss://mock.livekit.local',
      token: 'mock-token',
      roomName: `interview_${sessionId}`,
    } satisfies JoinSessionResponse;
  }

  const state = /^\/api\/v1\/sessions\/([^/]+)$/.exec(path);
  if (state && method === 'GET') {
    await delay(200);
    return {
      sessionId: state[1],
      interviewId: 'int_mock',
      status: 'INTERVIEWING',
      startedAt: new Date().toISOString(),
      endedAt: null,
    } satisfies SessionState;
  }

  const end = /^\/api\/v1\/sessions\/([^/]+)\/end$/.exec(path);
  if (end && method === 'POST') {
    await delay(300);
    return {
      sessionId: end[1],
      status: 'ENDED',
      endedAt: new Date().toISOString(),
    };
  }

  return null;
}
