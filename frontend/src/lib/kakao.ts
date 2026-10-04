/**
 * 카카오 인가 요청.
 *
 * 인가 URL 을 만들고 `state` 로 CSRF 를 막는 것은 **FE 몫**이다 — 인가 요청을 보낸 쪽만
 * 그 값을 알기 때문이다. 돌아온 `state` 가 보낸 값과 다르면 우리가 시작한 로그인이 아니다.
 *
 * `client_id`(REST API 키)는 인가 URL 에 그대로 실려 가는 값이라 비밀이 아니다.
 * 비밀인 `client_secret` 은 BE 에만 있고, 코드 → 토큰 교환도 BE 가 한다.
 */

const AUTHORIZE_URL = 'https://kauth.kakao.com/oauth/authorize';

/** 돌아왔을 때 비교할 state 를 둘 곳. 탭을 닫으면 사라져야 한다. */
const STATE_KEY = 'kakaoOAuthState';

export const KAKAO_CLIENT_ID = import.meta.env.VITE_KAKAO_CLIENT_ID ?? '';

/**
 * 콜백 주소. 카카오 콘솔에 등록된 값과 **글자 하나까지 같아야** 한다.
 * BE 의 토큰 교환도 같은 값을 쓴다 (`kakao_redirect_uri`).
 */
export const KAKAO_REDIRECT_URI =
  import.meta.env.VITE_KAKAO_REDIRECT_URI?.trim() ||
  `${window.location.origin}/oauth/kakao/callback`;

/** 키가 없으면 인가 URL 을 만들 수 없다. 화면이 미리 알려 주기 위해 노출한다. */
export const kakaoConfigured = Boolean(KAKAO_CLIENT_ID);

function newState(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * 인가 화면으로 보낼 주소를 만들고, 비교용 state 를 보관한다.
 *
 * 호출할 때마다 새 state 를 쓴다 — 재사용하면 이전 요청의 응답도 통과한다.
 */
export function buildKakaoAuthorizeUrl(): string {
  const state = newState();
  sessionStorage.setItem(STATE_KEY, state);

  const params = new URLSearchParams({
    client_id: KAKAO_CLIENT_ID,
    redirect_uri: KAKAO_REDIRECT_URI,
    response_type: 'code',
    state,
  });
  return `${AUTHORIZE_URL}?${params}`;
}

/**
 * 돌아온 state 를 확인한다. 한 번 쓰면 지운다 — 같은 값으로 두 번 통과하면 안 된다.
 *
 * 보관된 값이 없을 때도 실패로 본다. 우리가 시작하지 않은 콜백이다.
 */
export function consumeKakaoState(returned: string | null): boolean {
  const saved = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(STATE_KEY);
  return Boolean(saved) && saved === returned;
}
