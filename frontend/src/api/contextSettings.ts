/**
 * 기업 컨텍스트 설정 저장 API.
 *
 * 문서 업로드(api/context.ts)와 달리 회사·직무·인재상 같은 텍스트 항목을 고친다.
 *
 * ⚠️ BE 명세에 없는 엔드포인트다. 목으로만 동작한다 (mocks/contextSettingsMock.ts).
 * 조회(GET /contexts/{id})는 아직 talentProfile 을 돌려주지 않는다 — 저장한 인재상을
 * 다시 읽어 올 곳이 없어, 화면은 새로 고치면 빈 칸에서 시작한다.
 */

// 목 조회는 talentProfile 을 돌려준다. 실제 API 응답은 병합 후 계약을 확인한다.

import { request } from './client';

const V1 = '/api/v1';

/** PATCH /api/v1/contexts/{contextId} 요청 본문 */
export interface ContextSettingsPatch {
  company: string;
  /** 기본 직무 — 면접을 만들 때 초깃값으로 쓴다 */
  role: string;
  /** AI 면접관이 참고할 추가 인재상·평가 포인트 */
  talentProfile: string;
}

/** PATCH /api/v1/contexts/{contextId} 응답 */
export interface ContextSettings extends ContextSettingsPatch {
  id: string;
}

export const updateContextSettings = (contextId: string, patch: ContextSettingsPatch) =>
  request<ContextSettings>(`${V1}/contexts/${contextId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
