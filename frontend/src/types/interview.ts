/**
 * 면접 도메인 타입.
 *
 * 엔드포인트·경로·파라미터는 BE 명세(2026-09-08)를 따른다.
 * 다만 명세에 **요청·응답 본문 스키마가 없어서**, 아래 인터페이스의 필드는
 * 명세의 "설명" 칸에서 유추한 것이다. ⚠️ 표시한 곳이 확정되면 함께 고친다.
 */

export type Speaker = 'interviewer' | 'candidate';

/** 입장 권한. Speaker 와 값이 같지만 의미가 다르다 — 이쪽은 권한이다. */
export type Role = 'interviewer' | 'candidate';

/** Session 진행 상태. `GET /api/v1/sessions/{id}` 가 돌려준다. */
export type SessionStatus =
  /** 생성됐으나 아직 시작 전 */
  | 'created'
  /** 면접 진행 중 */
  | 'in-progress'
  /** 종료됨 */
  | 'ended';

/* ---------------------------------------------------------------- *
 * 면접 (면접관)
 * ---------------------------------------------------------------- */

/** GET /api/v1/interviews/{interviewId} */
export interface Interview {
  interviewId: string;
  /** ⚠️ 필드 구성 미확정 — 명세에 "면접의 기본 정보" 로만 적혀 있다 */
  candidateName: string;
  createdAt: string;
}

/**
 * POST /api/v1/interviews/{interviewId}/sessions
 * Session 을 만들고 지원자 초대 링크를 발급한다.
 */
export interface CreateSessionResponse {
  sessionId: string;
  /** ⚠️ 서버가 완성된 URL 을 주는지, FE 가 sessionId 로 조립하는지 미확정 */
  inviteUrl: string;
}

/** GET /api/v1/sessions/{sessionId} — 새로고침·재접속 시 상태 복구용 */
export interface SessionState {
  sessionId: string;
  status: SessionStatus;
  /** ⚠️ 미확정. 재입장 시 역할을 알아야 화면을 고를 수 있다 */
  role: Role;
}

/** POST /api/v1/sessions/{sessionId}/end */
export interface EndSessionResponse {
  durationSec: number;
  reviewStatus: 'processing' | 'ready';
}

/* ---------------------------------------------------------------- *
 * 진입
 * ---------------------------------------------------------------- */

/**
 * POST /api/v1/sessions/{sessionId}/join
 * "Session 입장 권한을 확인하고 LiveKit 접속 정보를 발급"
 *
 * ⚠️ 응답 본문이 명세에 없다. 아래는 프로토타입이 이미 파싱하던 형태다.
 * ⚠️ `role` 은 BE 가 #9 코멘트에서 "실어 보내는 게 맞다" 고 했으나 표에는 없다.
 * ⚠️ `stream`(전사 WebSocket) 은 명세 어디에도 없다 — AI #7 경로가 통째로 빠져 있다.
 */
export interface JoinSessionResponse {
  sessionId: string;
  role: Role;
  media: { roomUrl: string; token: string };
  stream: { url: string } | null;
}

/**
 * join 실패 사유.
 * ⚠️ 실제 코드 문자열은 여전히 미확정이다. 매핑은 api/interview.ts 한 곳에 모아둔다.
 */
export type JoinFailure =
  /** 존재하지 않는 세션 */
  | 'not-found'
  /** 입장 권한 없음 */
  | 'forbidden'
  /** 이미 종료된 세션 */
  | 'ended'
  /** 정원 초과 */
  | 'full'
  /** 그 외 (네트워크 포함) */
  | 'failed';

/* ---------------------------------------------------------------- *
 * 통화 중 (전사·추천 질문)
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
