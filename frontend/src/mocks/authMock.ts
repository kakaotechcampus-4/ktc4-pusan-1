/**
 * 인증 목.
 *
 * ⚠️ BE 에 인증 API 가 없어 로그인 화면이 혼자 돌게 만든 임시 코드다.
 * mockApi.ts 의 handleMock 과 같은 규칙을 쓴다 — 맞는 경로가 없으면 null 을 돌려주고,
 * 호출부가 그다음(실제 fetch)으로 넘어간다.
 *
 * ⚠️ 실제 인증이 붙으면 이 파일과 client.ts 의 분기를 함께 지운다.
 */

import type { LoginResponse } from '../api/auth';

/** 실제 서버처럼 보이도록 약간의 지연을 준다. 버튼의 진행 상태가 화면에 드러나야 한다. */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * 데모용 실패 경로.
 *
 * 목이 전부 성공하면 실패 문구를 확인할 방법이 없다. mockApi 가 세션 id 로 에러 화면을
 * 열어 두는 것과 같은 장치다.
 */
const WRONG_PASSWORD = 'fail';

export async function handleAuthMock(path: string, init?: RequestInit): Promise<unknown | null> {
  const method = init?.method ?? 'GET';

  if (path === '/api/v1/auth/login' && method === 'POST') {
    await delay(600);
    const body = JSON.parse(String(init?.body ?? '{}')) as { email?: string; password?: string };

    if (!body.email?.trim() || !body.password || body.password === WRONG_PASSWORD) {
      throw { status: 401 };
    }

    return { accessToken: `mock-token-${Date.now()}` } satisfies LoginResponse;
  }

  return null;
}
