const PREFIX = 'irya.memo.';

export const memoDraftKey = (ownerId: string, interviewId: string) =>
  PREFIX + JSON.stringify([ownerId, interviewId]);

export function readMemoDraft(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeMemoDraft(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // 저장소가 막혀도 서버 저장과 현재 화면의 입력은 유지한다.
  }
}

export function clearMemoDrafts() {
  try {
    for (const key of Object.keys(sessionStorage))
      if (key.startsWith(PREFIX)) sessionStorage.removeItem(key);
  } catch {
    // 계정 전환 시 서버 인증과 메모리 큐 정리는 저장소와 별도로 처리한다.
  }
}
