import type {
  EndSessionResponse,
  JoinFailure,
  JoinSessionResponse,
  StartInterviewResponse,
} from '../types/interview';
import { ApiError, request } from './client';

/**
 * 방 코드로 입장한다. 유일한 진입 API 다 (issue #9).
 *
 * 코드는 정규화된 8자를 넘긴다 — 하이픈은 표시용이므로 여기까지 오면 안 된다.
 */
export const joinSession = (code: string) =>
  request<JoinSessionResponse>('/sessions/join', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });

/**
 * 서버 에러 코드를 화면이 구분할 수 있는 사유로 바꾼다.
 *
 * ⚠️ 좌변의 문자열은 BE 미확정이다 (issue #9). 명세가 나오면 이 표만 고치면 되도록
 * 매핑을 여기 한 곳에 모아둔다 — 화면은 JoinFailure 만 안다.
 */
const FAILURE_BY_CODE: Record<string, JoinFailure> = {
  CODE_NOT_FOUND: 'not-found',
  CODE_EXPIRED: 'expired',
  SESSION_ENDED: 'ended',
  ROOM_FULL: 'full',
};

export function toJoinFailure(error: unknown): JoinFailure {
  if (!(error instanceof ApiError)) return 'failed';
  // 404 를 코드 미존재로 보는 것도 잠정이다. 명세 확정 시 함께 정리한다.
  if (error.status === 404) return FAILURE_BY_CODE[error.code] ?? 'not-found';
  return FAILURE_BY_CODE[error.code] ?? 'failed';
}

/** 방 생성 + 토큰 발급. 방 생성은 서버가 담당한다. */
export const startInterview = (interviewId: string) =>
  request<StartInterviewResponse>(`/interviews/${interviewId}/start`, { method: 'POST' });

export const endSession = (sessionId: string) =>
  request<EndSessionResponse>(`/sessions/${sessionId}/end`, { method: 'POST' });

export const askSuggestion = (sessionId: string, suggestionId: string) =>
  request<void>(`/sessions/${sessionId}/suggestions/${suggestionId}/ask`, { method: 'POST' });
