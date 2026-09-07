/** 면접 도메인 타입 — 서버 인터페이스 명세 §3, §4 */

export type Speaker = 'interviewer' | 'candidate';

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
