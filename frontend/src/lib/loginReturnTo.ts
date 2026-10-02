const KEY = 'irya:login-return-to';

/** 외부 주소나 로그인 콜백으로 돌아가면 안 된다. 앱 경로만 보관한다. */
export function safeLoginReturnTo(value: unknown, origin: string): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/';
  try {
    const url = new URL(value, origin);
    if (
      url.origin !== origin ||
      value.includes('\\') ||
      [...value].some((c) => c.charCodeAt(0) < 32)
    )
      return '/';
    const path = url.pathname.toLowerCase().replace(/\/+$/, '');
    if (path === '/login' || path === '/oauth' || path.startsWith('/oauth/')) return '/';
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return '/';
  }
}

/** 카카오를 다녀오는 동안 라우터 state가 사라지므로 탭에만 남긴다. */
export function rememberLoginReturnTo(value: unknown) {
  sessionStorage.setItem(KEY, safeLoginReturnTo(value, window.location.origin));
}

export function readLoginReturnTo(): string {
  return safeLoginReturnTo(sessionStorage.getItem(KEY), window.location.origin);
}

export function clearLoginReturnTo() {
  sessionStorage.removeItem(KEY);
}

export function consumeLoginReturnTo(): string {
  const path = readLoginReturnTo();
  clearLoginReturnTo();
  return path;
}
