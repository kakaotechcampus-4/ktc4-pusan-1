/**
 * 방 코드 형식 — BE 와 합의한 규칙 (issue #9).
 *
 *   길이   8자
 *   문자   A~Z 에서 O·I·L 제외(23자) + 0~9 에서 0·1 제외(8자) = 31자
 *   표시   ABCD-EFGH
 *   전송   하이픈 없이 8자
 *
 * 혼동 문자를 뺀 이유는 면접관이 지원자에게 구두나 채팅으로 코드를 불러주는 상황
 * 때문이다. O/0, I/1/L 이 섞이면 받아적는 쪽에서 틀린다.
 *
 * 서버도 같은 정규화를 독립적으로 수행한다. 여기의 검증은 왕복 한 번을 아끼기 위한
 * 것이지 보안 경계가 아니다 — 형식이 맞아도 존재하지 않는 코드일 수 있다.
 */

/** 코드에 쓰이는 문자 31개 */
export const CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';

export const CODE_LENGTH = 8;

/** 표시할 때 하이픈을 넣는 위치 */
const GROUP_SIZE = 4;

const VALID = new RegExp(`^[${CODE_ALPHABET}]{${CODE_LENGTH}}$`);

/**
 * 사용자 입력을 전송용 형태로 바꾼다.
 * 대문자로 올리고 하이픈·공백을 제거한다. 붙여넣기로 `abcd-efgh` 가 들어와도 통과한다.
 */
export function normalizeCode(input: string): string {
  return input.toUpperCase().replace(/[\s-]/g, '');
}

/** 정규화된 코드가 형식에 맞는지. 존재 여부는 서버만 안다. */
export function isValidCode(normalized: string): boolean {
  return VALID.test(normalized);
}

/** 화면 표시용. `ABCD-EFGH` 로 끊는다. 짧으면 있는 만큼만 끊는다. */
export function formatCode(normalized: string): string {
  const groups: string[] = [];
  for (let i = 0; i < normalized.length; i += GROUP_SIZE) {
    groups.push(normalized.slice(i, i + GROUP_SIZE));
  }
  return groups.join('-');
}

/**
 * 입력 중 걸러낼 문자를 판별한다.
 * 정규화 후 허용 문자 집합에 없는 것 — 예: O, I, L, 0, 1, 특수문자.
 */
export function rejectedChars(input: string): string[] {
  const seen = new Set<string>();
  for (const ch of normalizeCode(input)) {
    if (!CODE_ALPHABET.includes(ch)) seen.add(ch);
  }
  return [...seen];
}
