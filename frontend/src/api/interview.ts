/**
 * 면접 API — BE 명세(2026-09-08) 기준.
 *
 * 업무 API 는 `/api/v1` 아래, 헬스 체크만 루트에 있다.
 */

import type {
  CreateSessionResponse,
  EndSessionResponse,
  Interview,
  JoinFailure,
  JoinSessionResponse,
  SessionState,
} from '../types/interview';
import { ApiError, request } from './client';

const V1 = '/api/v1';

/* ---------------- 면접 (면접관) ---------------- */

/** 새 면접 정보를 만든다. Session·LiveKit Room 은 여기서 만들지 않는다. */
export const createInterview = () => request<Interview>(`${V1}/interviews`, { method: 'POST' });

export const getInterview = (interviewId: string) =>
  request<Interview>(`${V1}/interviews/${interviewId}`);

/** 화상면접 Session 을 만들고 지원자 초대 링크를 발급받는다. */
export const createSession = (interviewId: string) =>
  request<CreateSessionResponse>(`${V1}/interviews/${interviewId}/sessions`, { method: 'POST' });

/**
 * Session 을 면접 진행 상태로 바꾸고 시작 시각을 기록한다.
 * 상태 전이만 한다 — LiveKit 토큰은 join 이 발급한다.
 */
export const startSession = (sessionId: string) =>
  request<void>(`${V1}/sessions/${sessionId}/start`, { method: 'POST' });

/**
 * 현재 진행 상태를 조회한다. 새로고침·재접속 시 상태 복구용이다.
 * 면접관과 지원자 모두 호출할 수 있다.
 */
export const getSessionState = (sessionId: string) =>
  request<SessionState>(`${V1}/sessions/${sessionId}`);

/**
 * Session 을 종료 상태로 바꾸고 종료 시각을 기록한다.
 *
 * 참가자 disconnect 와 면접 종료는 별개다 — 브라우저를 닫아도 세션은 살아 있으므로
 * 종료는 반드시 명시적으로 호출해야 한다.
 */
export const endSession = (sessionId: string) =>
  request<EndSessionResponse>(`${V1}/sessions/${sessionId}/end`, { method: 'POST' });

/* ---------------- 진입 ---------------- */

/**
 * 입장 권한을 확인하고 LiveKit 접속 정보를 받는다.
 * 지원자는 초대 링크에서 sessionId 를 전달받는다.
 */
export const joinSession = (sessionId: string) =>
  request<JoinSessionResponse>(`${V1}/sessions/${sessionId}/join`, { method: 'POST' });

/**
 * 서버 에러를 화면이 구분할 수 있는 사유로 바꾼다.
 *
 * ⚠️ 좌변의 코드 문자열은 BE 미확정이다. 명세가 나오면 이 표만 고치면 되도록
 * 매핑을 여기 한 곳에 모아둔다 — 화면은 JoinFailure 만 안다.
 */
const FAILURE_BY_CODE: Record<string, JoinFailure> = {
  SESSION_NOT_FOUND: 'not-found',
  SESSION_ENDED: 'ended',
  ROOM_FULL: 'full',
  FORBIDDEN: 'forbidden',
};

/** ⚠️ status 기반 추정도 잠정이다. 명세 확정 시 위 표와 함께 정리한다. */
const FAILURE_BY_STATUS: Record<number, JoinFailure> = {
  403: 'forbidden',
  404: 'not-found',
  409: 'full',
  410: 'ended',
};

export function toJoinFailure(error: unknown): JoinFailure {
  if (!(error instanceof ApiError)) return 'failed';
  return FAILURE_BY_CODE[error.code] ?? FAILURE_BY_STATUS[error.status] ?? 'failed';
}
