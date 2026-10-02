/**
 * 기업 컨텍스트 API (S1).
 *
 * 조회는 `current` 하나로 한다 — 설정 화면에 들어올 때 FE 는 contextId 를 모른다.
 * 서버가 없으면 만들어서 돌려주므로, FE 는 "아직 안 만들었다" 와 "비어 있다" 를 구분하지 않는다.
 */

import type { CompanyContext, ContextDoc } from '../types/interview';
import { handleMockUpload, USE_MOCK_API } from '../mocks/mockApi';
import { request, uploadFile } from './client';

const V1 = '/api/v1';

/** GET /api/v1/contexts/current — 로그인한 사람의 조직 컨텍스트 */
export const getCurrentContext = () => request<CompanyContext>(`${V1}/contexts/current`);

export const deleteDoc = (contextId: string, docId: string) =>
  request<void>(`${V1}/contexts/${contextId}/docs/${docId}`, { method: 'DELETE' });

/**
 * 문서를 올린다.
 *
 * `fetch` 는 업로드 진행률을 알려주지 않는다. 50MB 까지 받는데 진행 표시가 없으면
 * 멈춘 것처럼 보이므로 XHR 을 쓴다.
 */
export function uploadDoc(
  contextId: string,
  file: File,
  onProgress: (ratio: number) => void,
): Promise<ContextDoc> {
  // ⚠️ 프로토타입 임시 분기. XHR 은 request() 를 거치지 않으므로 여기서 따로 가른다.
  if (USE_MOCK_API) return handleMockUpload(file, onProgress);

  return uploadFile(`${V1}/contexts/${contextId}/docs`, file, onProgress);
}
