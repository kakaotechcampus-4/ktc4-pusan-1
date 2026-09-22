/**
 * 기업 컨텍스트 설정 저장 목.
 *
 * mockApi.ts 의 handleMock 과 같은 규칙이다 — 맞는 경로가 없으면 null 을 돌려준다.
 * 같은 경로의 GET(컨텍스트 조회)은 mockApi 가 맡고 있어, 여기서는 PATCH 만 가른다.
 *
 * ⚠️ 저장 API 가 생기면 이 파일과 client.ts 의 분기를 함께 지운다.
 */

import type { ContextSettings, ContextSettingsPatch } from '../api/contextSettings';
import { contextProfile } from './contextStore';

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function handleContextSettingsMock(
  path: string,
  init?: RequestInit,
): Promise<unknown | null> {
  const method = init?.method ?? 'GET';
  const context = /^\/api\/v1\/contexts\/([^/]+)$/.exec(path);

  if (context && method === 'PATCH') {
    await delay(500);
    const contextId = context[1];
    const patch = JSON.parse(String(init?.body ?? '{}')) as Partial<ContextSettingsPatch>;

    // 보관소에 반영한다. 조회(GET /contexts/{id})가 같은 값을 보므로 저장이 유지된다.
    if (patch.company !== undefined) contextProfile.company = patch.company;
    if (patch.role !== undefined) contextProfile.role = patch.role;
    if (patch.talentProfile !== undefined) contextProfile.talentProfile = patch.talentProfile;

    return {
      id: contextId,
      company: contextProfile.company,
      role: contextProfile.role,
      talentProfile: contextProfile.talentProfile,
    } satisfies ContextSettings;
  }

  return null;
}
