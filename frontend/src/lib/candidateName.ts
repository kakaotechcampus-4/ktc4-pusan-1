/** 이름이 없을 때 화면에 쓰는 값 */
export const FALLBACK_CANDIDATE = '지원자';

/** 지원자에게 보이는 상대 이름. 면접관 실명은 알려주지 않는다. */
export const INTERVIEWER_LABEL = '면접관';

export function normalizeCandidateName(name: string): string | undefined {
  return name.trim() || undefined;
}
