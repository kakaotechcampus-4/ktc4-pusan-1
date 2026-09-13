/**
 * API base URL.
 *
 * 명세의 경로는 두 갈래다 — 업무 API 는 `/api/v1/...`, 헬스 체크는 `/health`.
 * 그래서 base 에는 prefix 를 넣지 않고 오리진만 둔다. prefix 는 각 호출 경로에 쓴다.
 */
import { handleMock, USE_MOCK_API } from '../mocks/mockApi';

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

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

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('accessToken') ?? ''}`,
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.error?.code ?? 'UNKNOWN', res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
