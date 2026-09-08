/**
 * 면접 도메인 타입 — BE 명세(docs/api) 기준.
 *
 * 응답 필드는 각 문서의 Response 표를 그대로 옮긴 것이다.
 * 명세에 없어서 FE 가 정한 부분은 ⚠️ 로 표시했다.
 */

export type Speaker = 'interviewer' | 'candidate';

/**
 * 입장 권한.
 *
 * 현재는 클라이언트가 join 요청에 실어 보낸다 (인증 도입 전 임시 구조).
 * 서버가 판단하도록 바뀌면 joinSession 호출부 한 곳만 고치면 된다.
 */
export type Role = 'INTERVIEWER' | 'CANDIDATE';

/** Session 진행 상태 */
export type SessionStatus = 'WAITING' | 'INTERVIEWING' | 'ENDED';

/* ---------------------------------------------------------------- *
 * 면접
 * ---------------------------------------------------------------- */

/** POST /api/v1/interviews · GET /api/v1/interviews/{interviewId} */
export interface Interview {
  interviewId: string;
  interviewerId: string;
  createdAt: string;
}

/** POST /api/v1/interviews/{interviewId}/sessions */
export interface CreateSessionResponse {
  sessionId: string;
  interviewId: string;
  status: SessionStatus;
  /** 지원자에게 전달할 면접 링크 */
  inviteUrl: string;
  createdAt: string;
}

/** POST /api/v1/sessions/{sessionId}/start */
export interface StartSessionResponse {
  sessionId: string;
  status: SessionStatus;
  startedAt: string;
}

/** GET /api/v1/sessions/{sessionId} — 새로고침·재접속 시 상태 복구용 */
export interface SessionState {
  sessionId: string;
  interviewId: string;
  status: SessionStatus;
  startedAt: string | null;
  endedAt: string | null;
}

/** POST /api/v1/sessions/{sessionId}/end */
export interface EndSessionResponse {
  sessionId: string;
  status: SessionStatus;
  endedAt: string;
}

/* ---------------------------------------------------------------- *
 * 진입
 * ---------------------------------------------------------------- */

/** POST /api/v1/sessions/{sessionId}/join */
export interface JoinSessionResponse {
  sessionId: string;
  /** LiveKit 서버 접속 URL */
  livekitUrl: string;
  /** LiveKit Room 입장용 Access Token */
  token: string;
  /** 매핑된 LiveKit Room 이름 */
  roomName: string;
}

/**
 * join 실패 사유.
 *
 * ⚠️ 명세에 에러 본문 스키마가 없어서 HTTP status 로만 구분한다.
 * 그래서 409 하나에 "이미 종료" 와 "정원 초과" 가 겹친다 — 문구를 합쳐 뒀다.
 * 서버가 `error.code` 를 주기 시작하면 api/interview.ts 의 표에 줄만 추가하면 된다.
 */
export type JoinFailure =
  /** 존재하지 않는 세션 */
  | 'not-found'
  /** 현재 상태에서 입장 불가 — 종료됨 또는 정원 초과 */
  | 'unavailable'
  /** 그 외 (네트워크 포함) */
  | 'failed';

/* ---------------------------------------------------------------- *
 * 통화 중 (전사·추천 질문)
 *
 * ⚠️ 이 WebSocket 경로는 명세에 없다 (AI #7). 아래 타입은 목 데이터가 쓴다.
 * ---------------------------------------------------------------- */

export interface Utterance {
  id: string;
  speaker: Speaker;
  text: string;
  atSec: number;
  final: boolean;
}

export interface Suggestion {
  id: string;
  text: string;
  reason: string;
  atSec: number;
  asked: boolean;
}

export type StreamEvent =
  | { type: 'speech.start'; speaker: Speaker; at: number }
  | { type: 'speech.end'; speaker: Speaker; at: number }
  | {
      type: 'transcript.delta';
      utteranceId: string;
      speaker: Speaker;
      text: string;
      at: number;
      final: boolean;
    }
  | {
      type: 'suggestion.created';
      id: string;
      text: string;
      reason: string;
      at: number;
    }
  | { type: 'stream.degraded'; reason: string };
