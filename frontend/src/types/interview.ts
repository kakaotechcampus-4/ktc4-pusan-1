/** 면접 도메인 타입 — 서버 인터페이스 명세 §3, §4 */

export type Speaker = 'interviewer' | 'candidate';

/** join 응답이 알려주는 역할. Speaker 와 값이 같지만 의미가 다르다 — 이쪽은 권한이다. */
export type Role = 'interviewer' | 'candidate';

/**
 * POST /sessions/join { code }
 *
 * ⚠️ 응답 스키마가 아직 확정되지 않았다 (issue #9).
 * BE 가 확정한 것은 `role` 이 실려 온다는 것뿐이고,
 * 나머지 필드는 기존 start 응답 형태를 그대로 쓴다고 가정한 것이다.
 * 명세가 나오면 이 타입과 pages/JoinPage 의 분기를 함께 고친다.
 */
export interface JoinSessionResponse {
  sessionId: string;
  role: Role;
  media: { roomUrl: string; token: string };
  /** 전사·추천 질문 WebSocket. AI #7 미완이면 null 로 내려온다 */
  stream: { url: string } | null;
}

/**
 * join 실패 사유.
 *
 * ⚠️ 실제 코드 문자열은 BE 미확정이다 (issue #9).
 * 화면 분기를 미리 만들어두기 위한 잠정 목록이며, 매핑은 api/interview.ts 한 곳에 모아둔다.
 */
export type JoinFailure =
  /** 형식은 맞으나 존재하지 않는 코드 */
  | 'not-found'
  /** 만료된 코드 */
  | 'expired'
  /** 이미 종료된 세션 */
  | 'ended'
  /** 정원 초과 */
  | 'full'
  /** 그 외 (네트워크 포함) */
  | 'failed';

/** POST /interviews/{id}/start */
export interface StartInterviewResponse {
  sessionId: string;
  media: { roomUrl: string; token: string };
  stream: { url: string };
}

/** POST /sessions/{id}/end */
export interface EndSessionResponse {
  durationSec: number;
  reviewStatus: 'processing' | 'ready';
}

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

/** stream WebSocket 수신 이벤트 */
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
