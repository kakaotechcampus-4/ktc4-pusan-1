/**
 * 액세스 토큰 보관.
 *
 * "로그인 상태 유지"를 켜면 localStorage(브라우저를 닫아도 남는다), 끄면
 * sessionStorage(탭을 닫으면 사라진다)에 둔다. 체크박스를 두고도 저장 위치가 같으면
 * 켜든 끄든 결과가 같아 의미 없는 선택지가 된다.
 *
 */

import { queryClient } from './queryClient';
import { clearLoginReturnTo } from './loginReturnTo';

const KEY = 'accessToken';
const TOKEN_CHANGED = 'irya:token-changed';

export function saveAccessToken(token: string, keepSignedIn: boolean) {
  const [target, other] = keepSignedIn
    ? [localStorage, sessionStorage]
    : [sessionStorage, localStorage];

  queryClient.clear();
  target.setItem(KEY, token);
  // 반대쪽에 남은 토큰을 지운다. 양쪽에 있으면 어느 것이 이번 로그인인지 알 수 없다.
  other.removeItem(KEY);
  window.dispatchEvent(new Event(TOKEN_CHANGED));
}

/** 탭 한정 토큰을 먼저 본다. 방금 한 로그인이 이쪽이다. */
export const readAccessToken = () => sessionStorage.getItem(KEY) ?? localStorage.getItem(KEY);

/** 토큰이 더 이상 쓸 수 없을 때(401) 양쪽에서 지운다. */
export function clearAccessToken() {
  clearLoginReturnTo();
  queryClient.clear();
  sessionStorage.removeItem(KEY);
  localStorage.removeItem(KEY);
  window.dispatchEvent(new Event(TOKEN_CHANGED));
}

/** 같은 탭의 저장과 다른 탭의 계정 변경을 함께 반영한다. */
export function subscribeAccessToken(onChange: () => void) {
  const storageChanged = (event: StorageEvent) => {
    if (event.storageArea !== localStorage || (event.key !== KEY && event.key !== null)) return;
    queryClient.clear();
    onChange();
  };
  window.addEventListener('storage', storageChanged);
  window.addEventListener(TOKEN_CHANGED, onChange);
  return () => {
    window.removeEventListener('storage', storageChanged);
    window.removeEventListener(TOKEN_CHANGED, onChange);
  };
}
