/**
 * 기업 컨텍스트 API (S1).
 *
 * ⚠️ BE 명세에 없는 엔드포인트다. 목으로만 동작한다.
 */

import type { CompanyContext, ContextDoc } from '../types/interview';
import { handleMockUpload, USE_MOCK_API } from '../mocks/mockApi';
import { API_BASE, ApiError, request } from './client';

const V1 = '/api/v1';

export const getContext = (contextId: string) =>
  request<CompanyContext>(`${V1}/contexts/${contextId}`);

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

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append('file', file);

    xhr.open('POST', `${API_BASE}${V1}/contexts/${contextId}/docs`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as ContextDoc);
        return;
      }
      reject(new ApiError('UPLOAD_FAILED', xhr.status));
    };
    xhr.onerror = () => reject(new ApiError('NETWORK', 0));
    xhr.send(form);
  });
}
