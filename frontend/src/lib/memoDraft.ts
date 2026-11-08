const PREFIX = 'irya.memo.';

export interface StoredMemoDraft {
  memo: string;
  baseline?: string;
}

export const memoDraftKey = (ownerId: string, interviewId: string) =>
  PREFIX + JSON.stringify([ownerId, interviewId]);

export function readMemoDraft(key: string): StoredMemoDraft | null {
  try {
    const value = sessionStorage.getItem(key);
    if (value === null) return null;
    try {
      const draft: unknown = JSON.parse(value);
      if (
        typeof draft === 'object' &&
        draft !== null &&
        'version' in draft &&
        draft.version === 1 &&
        'memo' in draft &&
        typeof draft.memo === 'string' &&
        'baseline' in draft &&
        (typeof draft.baseline === 'string' || draft.baseline === null)
      )
        return { memo: draft.memo, baseline: draft.baseline ?? undefined };
    } catch {
      // 이전 버전의 본문만 저장한 초안도 잃지 않는다.
    }
    return { memo: value };
  } catch {
    return null;
  }
}

export function writeMemoDraft(key: string, value: StoredMemoDraft | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else
      sessionStorage.setItem(
        key,
        JSON.stringify({ version: 1, ...value, baseline: value.baseline ?? null }),
      );
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
