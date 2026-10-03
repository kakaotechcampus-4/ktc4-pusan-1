/**
 * 지원자 이력서 API.
 *
 *   POST /api/v1/interviews/{interviewId}/resume   multipart/form-data · field: file
 *
 * 면접 한 건에 이력서는 한 장이므로 목록·삭제는 두지 않았다. 다시 올리면 덮어쓴다고 본다.
 */

import type { ContextDoc } from '../types/interview';
import { USE_MOCK_API } from '../mocks/mockApi';
import { handleMockResumeUpload } from '../mocks/resumeMock';
import { uploadFile } from './client';

const V1 = '/api/v1';

/**
 * 이력서를 올린다. 응답은 문서 한 건이라 컨텍스트 문서와 같은 모양(ContextDoc)을 쓴다.
 *
 * `fetch` 는 업로드 진행률을 알려주지 않는다. 50MB 까지 받는데 진행 표시가 없으면
 * 멈춘 것처럼 보이므로 XHR 을 쓴다 (api/context.ts 의 uploadDoc 과 같은 이유다).
 */
export function uploadResume(
  interviewId: string,
  file: File,
  onProgress: (ratio: number) => void,
): Promise<ContextDoc> {
  // ⚠️ 프로토타입 임시 분기. XHR 은 request() 를 거치지 않으므로 여기서 따로 가른다.
  if (USE_MOCK_API) return handleMockResumeUpload(file, onProgress);

  return uploadFile(`${V1}/interviews/${interviewId}/resume`, file, onProgress);
}
