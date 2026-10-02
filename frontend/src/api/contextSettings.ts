/**
 * 기업 컨텍스트 설정 저장 API.
 *
 * 문서 업로드(api/context.ts)와 달리 회사·직무·인재상 같은 텍스트 항목을 고친다.
 *
 */

import { request } from './client';

const V1 = '/api/v1';

/** PATCH /api/v1/contexts/{contextId} 요청 본문 */
export interface ContextSettingsPatch {
  company: string;
  team: string;
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
