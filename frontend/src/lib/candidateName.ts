/**
 * 지원자 이름 임시 보관.
 *
 * ⚠️ 서버에 이름 필드가 없어서 브라우저에 둔다. BE 스키마에 `candidateName` 이
 * 생기면 이 파일을 지우고 `createInterview` 요청과 `join` 응답으로 옮긴다.
 *
 * sessionStorage 를 쓰는 이유:
 *   - 새로고침해도 남는다. useState 로 두면 F5 한 번에 이름이 사라진다
 *   - 탭을 닫으면 지워진다. 면접이 끝난 뒤까지 남길 값이 아니다
 *   - 세션마다 따로 둔다. 면접관이 여러 면접을 번갈아 봐도 섞이지 않는다
 */

const KEY = (sessionId: string) => `irya:candidateName:${sessionId}`;

/** 이름이 없을 때 화면에 쓰는 값 */
export const FALLBACK_CANDIDATE = '지원자';

/** 지원자에게 보이는 상대 이름. 면접관 실명은 알려주지 않는다. */
export const INTERVIEWER_LABEL = '면접관';

export function saveCandidateName(sessionId: string, name: string): void {
  const trimmed = name.trim();
  if (!trimmed) return;
  try {
    sessionStorage.setItem(KEY(sessionId), trimmed);
  } catch {
    // 시크릿 모드나 저장 용량 초과. 이름이 안 보일 뿐 면접은 진행된다.
  }
}

export function loadCandidateName(sessionId: string | undefined): string {
  if (!sessionId) return FALLBACK_CANDIDATE;
  try {
    return sessionStorage.getItem(KEY(sessionId)) ?? FALLBACK_CANDIDATE;
  } catch {
    return FALLBACK_CANDIDATE;
  }
}
