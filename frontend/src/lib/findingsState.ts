/**
 * 검토 항목이 실패한 면접과 비어 있는 면접을 다르게 말한다 (#244).
 *
 * 실패를 「없음」으로 보이면 면접관은 그것을 지원자의 역량 판단으로 읽는다.
 */

import type { Coverage, FindingsStatus } from '../types/interview';

const COVERAGE_LABEL: Record<Coverage['state'], string> = {
  CONFIRMED: '확인',
  PARTIAL: '일부',
  MISSING: '없음',
};

export function coverageLabel(state: Coverage['state'], status: FindingsStatus): string {
  return status === 'FAILED' && state === 'MISSING' ? '확인 불가' : COVERAGE_LABEL[state];
}

/** 판단 진행 문구. 만들지 못했으면 「모두 판단했습니다」가 거짓이라 null 이다 */
export function progressNote(open: number, status: FindingsStatus): string | null {
  if (status === 'FAILED') return null;
  return open > 0 ? `${open}건이 아직 판단 전입니다` : '모두 판단했습니다';
}
