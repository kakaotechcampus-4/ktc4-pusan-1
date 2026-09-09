/**
 * 면접 API — BE API 명세 기준.
 *
 * 업무 API 는 `/api/v1` 아래, 헬스 체크만 루트에 있다.
 */

import type {
  CreateSessionResponse,
  EndSessionResponse,
  Interview,
  InterviewSummary,
  JoinFailure,
  JoinSessionResponse,
  Role,
  SessionState,
  StartSessionResponse,
} from '../types/interview';
import { ApiError, request } from './client';

const V1 = '/api/v1';

/* ---------------- 면접 ---------------- */

/** 새 면접 정보를 만든다. Session·LiveKit Room 은 여기서 만들지 않는다. */
export const createInterview = (interviewerId: string) =>
  request<Interview>(`${V1}/interviews`, {
    method: 'POST',
    body: JSON.stringify({ interviewerId }),
  });

export const getInterview = (interviewId: string) =>
  request<Interview>(`${V1}/interviews/${interviewId}`);

/** 화상면접 Session 을 만들고 지원자 초대 링크(inviteUrl)를 발급받는다. */
export const createSession = (interviewId: string) =>
  request<CreateSessionResponse>(`${V1}/interviews/${interviewId}/sessions`, { method: 'POST' });

/**
 * Session 을 면접 진행 상태로 바꾸고 시작 시각을 기록한다.
 * 상태 전이만 한다 — LiveKit 토큰은 join 이 발급한다.
 */
export const startSession = (sessionId: string) =>
  request<StartSessionResponse>(`${V1}/sessions/${sessionId}/start`, { method: 'POST' });

/** 현재 진행 상태를 조회한다. 새로고침·재접속 시 상태 복구용이다. */
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

/**
 * 면접 요약을 조회한다 (이슈 #6).
 *
 * ⚠️ 아직 명세에 없는 엔드포인트다. 생성 중이면 status 가 PROCESSING 으로 오므로
 * 화면이 잠시 뒤 다시 부른다.
 */
export const getSummary = (sessionId: string) =>
  request<InterviewSummary>(`${V1}/sessions/${sessionId}/summary`);

/* ---------------- 진입 ---------------- */

/**
 * 입장 권한을 확인하고 LiveKit 접속 정보를 받는다.
 *
 * ⚠️ role 을 클라이언트가 선언하는 구조다 (인증 도입 전 임시).
 * 서버가 판단하도록 바뀌면 이 함수의 시그니처만 좁히면 된다.
 */
export const joinSession = (sessionId: string, role: Role) =>
  request<JoinSessionResponse>(`${V1}/sessions/${sessionId}/join`, {
    method: 'POST',
    body: JSON.stringify({ role }),
  });

/**
 * 서버 에러를 화면이 구분할 수 있는 사유로 바꾼다.
 *
 * ⚠️ 명세에 에러 본문 스키마가 없어 지금은 HTTP status 로만 구분한다.
 *    409 는 "이미 종료" 와 "정원 초과" 가 겹치므로 하나로 묶었다.
 *    서버가 `error.code` 를 주기 시작하면 FAILURE_BY_CODE 에 줄만 추가하면 된다.
 */
const FAILURE_BY_CODE: Record<string, JoinFailure> = {};

const FAILURE_BY_STATUS: Record<number, JoinFailure> = {
  404: 'not-found',
  409: 'unavailable',
};

export function toJoinFailure(error: unknown): JoinFailure {
  if (!(error instanceof ApiError)) return 'failed';
  return FAILURE_BY_CODE[error.code] ?? FAILURE_BY_STATUS[error.status] ?? 'failed';
}
