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

import type { JoinSessionResponse, SessionState } from '../types/interview';

/** 목이 켜져 있는가. 개발 모드에서만, 명시적으로 끄지 않은 경우에 동작한다. */
export const USE_MOCK_API = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK_API !== 'false';

/** 실제 서버처럼 보이도록 약간의 지연을 준다. 로딩 상태가 화면에 드러나야 한다. */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 경로 → 응답. 실제 라우팅과 같은 모양으로 맞춰 둔다.
 * 매칭되지 않으면 null 을 돌려주고 호출부가 실제 fetch 로 넘어간다.
 */
export async function handleMock(path: string, init?: RequestInit): Promise<unknown | null> {
  const method = init?.method ?? 'GET';

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
