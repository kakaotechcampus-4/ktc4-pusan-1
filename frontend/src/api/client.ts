/**
 * API base URL.
 *
 * 명세의 경로는 두 갈래다 — 업무 API 는 `/api/v1/...`, 헬스 체크는 `/health`.
 * 그래서 base 에는 prefix 를 넣지 않고 오리진만 둔다. prefix 는 각 호출 경로에 쓴다.
 */
import { handleMock, USE_MOCK_API } from '../mocks/mockApi';
import { clearAccessToken, readAccessToken } from '../lib/authToken';
import { parseContextDoc } from '../lib/docFile';
import type { ContextDoc, DocCategory } from '../types/interview';

export const API_BASE =
  import.meta.env.VITE_API_BASE?.trim() || (import.meta.env.DEV ? 'http://localhost:8000' : '');

export const authorizationHeader = () => `Bearer ${readAccessToken() ?? ''}`;

export class ApiError extends Error {
  // 파라미터 프로퍼티는 erasableSyntaxOnly 에서 막히므로 필드를 명시한다.
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number) {
    super(code);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // ⚠️ 프로토타입 임시 분기. BE 연동 시 이 블록과 mocks/mockApi.ts 를 함께 지운다.
  if (USE_MOCK_API) {
    try {
      const mocked = await handleMock(path, init);
      if (mocked !== null) return mocked as T;
    } catch (e) {
      const status = (e as { status?: number }).status ?? 500;
      throw new ApiError('MOCK', status);
    }
  }

  const accessToken = readAccessToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken ?? ''}`,
      ...init?.headers,
    },
  });
  if (!res.ok) {
    if (res.status === 401 && accessToken && readAccessToken() === accessToken) clearAccessToken();
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.error?.code ?? 'UNKNOWN', res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

/** 문서와 이력서가 같은 업로드 계약을 쓴다. 오류·인증 처리가 갈라지지 않게 둔다. */
export function uploadFile(
  path: string,
  file: File,
  onProgress: (ratio: number) => void,
  category?: DocCategory,
): Promise<ContextDoc> {
  const accessToken = readAccessToken();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append('file', file);
    // 이력서에는 칸이 없다. 보내지 않으면 서버가 기본값(internal)을 쓴다.
    if (category) form.append('category', category);
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.setRequestHeader('Authorization', `Bearer ${accessToken ?? ''}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const doc = parseContextDoc(xhr.responseText);
        if (doc) resolve(doc);
        else reject(new ApiError('INVALID_RESPONSE', xhr.status));
        return;
      }
      // 이전 업로드의 늦은 401로 새 로그인까지 지우지 않는다.
      if (xhr.status === 401 && accessToken && readAccessToken() === accessToken)
        clearAccessToken();
      let code = 'UPLOAD_FAILED';
      try {
        const body = JSON.parse(xhr.responseText);
        if (typeof body?.error?.code === 'string') code = body.error.code;
      } catch {
        // 프록시가 HTML 오류를 줘도 요청은 실패로 끝낸다.
      }
      reject(new ApiError(code, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError('NETWORK', 0));
    xhr.onabort = () => reject(new ApiError('ABORTED', 0));
    xhr.send(form);
  });
}

export function uploadErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return '50MB 이하 파일만 올릴 수 있습니다.';
    if (error.status === 415) return 'PDF 만 올릴 수 있습니다.';
    if (error.status === 422) return '빈 파일인지, 파일 이름이 올바른지 확인해주세요.';
    if (error.status === 401) return '로그인 상태를 다시 확인해주세요.';
  }
  return '올리지 못했습니다. 잠시 후 다시 시도해주세요.';
}
