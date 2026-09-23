/**
 * 액세스 토큰 보관.
 *
 * "로그인 상태 유지"를 켜면 localStorage(브라우저를 닫아도 남는다), 끄면
 * sessionStorage(탭을 닫으면 사라진다)에 둔다. 체크박스를 두고도 저장 위치가 같으면
 * 켜든 끄든 결과가 같아 의미 없는 선택지가 된다.
 *
 * ⚠️ api/client.ts 의 authorizationHeader() 는 지금 localStorage 만 읽는다.
 * 유지를 끈 로그인도 헤더에 실리게 하려면 그쪽이 readAccessToken() 을 쓰도록 바꿔야 한다.
 */

// 현재 client.ts 는 readAccessToken()으로 두 저장소를 확인한다.

const KEY = 'accessToken';

export function saveAccessToken(token: string, keepSignedIn: boolean) {
  const [target, other] = keepSignedIn
    ? [localStorage, sessionStorage]
    : [sessionStorage, localStorage];

  target.setItem(KEY, token);
  // 반대쪽에 남은 토큰을 지운다. 양쪽에 있으면 어느 것이 이번 로그인인지 알 수 없다.
  other.removeItem(KEY);
}

/** 탭 한정 토큰을 먼저 본다. 방금 한 로그인이 이쪽이다. */
export const readAccessToken = () => sessionStorage.getItem(KEY) ?? localStorage.getItem(KEY);
