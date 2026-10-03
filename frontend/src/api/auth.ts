/**
 * 인증 API (#119, #126).
 *
 * 카카오 인가 화면에서 받은 `code` 를 BE 에 넘기면 우리 서비스의 토큰이 나온다.
 * 카카오와 직접 토큰을 교환하는 쪽은 BE 다 — client_secret 이 서버에만 있어야 한다.
 */

import { request } from './client';

const V1 = '/api/v1';

/** GET /api/v1/auth/me · 로그인 응답에 함께 온다 */
export interface User {
  id: string;
  /** 카카오 닉네임. 콘솔에서 필수 동의 항목이다 */
  nickname: string;
  profileImageUrl: string | null;
}

/** POST /api/v1/auth/kakao */
export interface LoginResponse {
  /** 이후 요청의 Authorization 헤더에 실린다 */
  accessToken: string;
  user: User;
}

/**
 * 카카오 로그인.
 *
 * `code` 는 한 번만 쓸 수 있다. 같은 코드로 두 번 부르면 401 이 온다 —
 * 콜백 화면이 두 번 실행되지 않도록 호출부가 막아야 한다.
 */
export const kakaoLogin = (code: string) =>
  request<LoginResponse>(`${V1}/auth/kakao`, {
    method: 'POST',
    body: JSON.stringify({ code }),
  });

/** 토큰이 아직 쓸 수 있는지 확인하고 내 정보를 가져온다. 만료·위조면 401 이다. */
export const getMe = () => request<User>(`${V1}/auth/me`);
