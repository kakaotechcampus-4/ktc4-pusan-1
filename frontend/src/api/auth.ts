/**
 * 인증 API.
 *
 * ⚠️ BE 명세에 없는 엔드포인트다. 로그인 화면을 붙일 수 있도록 FE 가 형태를 먼저 정했다.
 * 목으로만 동작한다 (mocks/authMock.ts).
 */

import { request } from './client';

const V1 = '/api/v1';

export interface LoginRequest {
  email: string;
  password: string;
}

/** POST /api/v1/auth/login */
export interface LoginResponse {
  /** 이후 요청의 Authorization 헤더에 실린다 */
  accessToken: string;
}

export const login = (body: LoginRequest) =>
  request<LoginResponse>(`${V1}/auth/login`, { method: 'POST', body: JSON.stringify(body) });
