const API_BASE = import.meta.env.VITE_API_BASE ?? 'https://api.irya.kr/v1';

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
