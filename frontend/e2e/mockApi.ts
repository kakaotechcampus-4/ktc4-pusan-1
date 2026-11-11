/**
 * 로그인 뒤 화면이 부르는 `/api` 를 모킹한다.
 *
 * 응답은 `src/types` 의 타입으로 쓴다. API 타입이 바뀌면 여기서 타입 검사가 깨져
 * 모킹이 실제 계약과 어긋난 채로 남지 않는다.
 */
import type { Page, Route } from '@playwright/test';
import type { User } from '../src/api/auth';
import type { CompanyContext, InterviewListResponse } from '../src/types/interview';

export const ME: User = { id: 'usr_e2e', nickname: '면접관', profileImageUrl: null };

export const CONTEXT: CompanyContext = {
  id: 'ctx_e2e',
  company: '이랴',
  team: '플랫폼',
  role: '백엔드 엔지니어',
  talentProfile: '',
  docs: [],
};

export const INTERVIEWS: InterviewListResponse = {
  items: [
    {
      interviewId: 'itv_e2e_1',
      candidateName: '김지원',
      role: '백엔드 엔지니어',
      interviewer: { nickname: ME.nickname },
      interviewedAt: '2026-11-08T05:00:00Z',
      durationSec: 1800,
      reviewStatus: 'PENDING',
      summaryStatus: null,
      counts: null,
    },
  ],
};

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

/** 토큰을 심는다. 앱은 sessionStorage 를 먼저, 없으면 localStorage 를 본다. */
export async function signIn(page: Page, token = 'e2e-token') {
  await page.addInitScript((value) => localStorage.setItem('accessToken', value), token);
}

/**
 * 기본 응답을 건다. `me` 를 `401` 로 주면 만료 토큰 흐름이 된다.
 * 모킹하지 않은 경로는 404 로 돌려 테스트가 실제 서버를 기대하지 않게 한다.
 */
export async function mockApi(page: Page, { me = 200 }: { me?: 200 | 401 } = {}) {
  await page.route('**/api/v1/**', (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    if (pathname === '/api/v1/auth/me')
      return me === 200
        ? json(route, 200, ME)
        : json(route, 401, { error: { code: 'UNAUTHORIZED', message: '' } });
    if (method === 'GET' && pathname === '/api/v1/interviews') return json(route, 200, INTERVIEWS);
    if (method === 'GET' && pathname === '/api/v1/contexts/current')
      return json(route, 200, CONTEXT);
    return json(route, 404, { error: { code: 'NOT_FOUND', message: '' } });
  });
}
