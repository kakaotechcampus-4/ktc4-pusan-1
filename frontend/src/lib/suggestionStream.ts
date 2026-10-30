/**
 * 꼬리질문 수신 (#212).
 *
 * 두 통로로 같은 것이 온다. 면접 중에는 BE 가 RoomService SendData 로 면접관에게만
 * 보내고(topic `irya.suggestion.v1`), 입장 · 재연결 · 종료 뒤에는 조회
 * API(`GET /sessions/{sessionId}/suggestions`)로 받는다. 명세가 두 본문을 같은 모양으로
 * 맞춰 두었으므로 읽는 코드도 하나로 둔다 — 한쪽만 고치는 일이 생기지 않게.
 *
 * 전사(`transcriptStream.ts`)와는 토픽 이름만 짝이고 받는 API 가 다르다. 전사는 text
 * stream 이지만 꼬리질문은 데이터 패킷이라 `RoomEvent.DataReceived` 로 받는다.
 * 보내는 쪽이 서버라서 그 이벤트의 `participant` 인자는 비어서 온다 —
 * 보낸 사람으로는 거를 수 없고 토픽만 본다.
 *
 * 명세의 `status` 와 `evidenceUtteranceIds` 는 받지 않는다. `status` 는 값이 `NEW`
 * 하나뿐이고 바꾸는 API 가 없다. 근거 발화는 Agent 가 인용한 순서로 와서 발화 순서가
 * 아니고, 화면에 남는 전사가 마지막 6줄뿐이라(`stores/interviewStore.ts`) 대부분
 * 이미 지나간 줄을 가리킨다.
 */

import type { Suggestion } from '../types/interview';

export const SUGGESTION_TOPIC = 'irya.suggestion.v1';

/**
 * 명세의 `SuggestionResponse` 하나를 화면이 쓰는 모양으로 바꾼다. 아니면 null.
 *
 * 하나가 깨져도 통화와 다음 꼬리질문은 계속 받아야 하므로 던지지 않는다.
 */
export function toSuggestion(value: unknown): Suggestion | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const { suggestionId, content, createdAt, reason } = value as Record<string, unknown>;

  if (typeof suggestionId !== 'string' || !suggestionId.trim()) return null;
  // 빈 질문은 올려도 면접관이 읽을 것이 없다.
  if (typeof content !== 'string' || !content.trim()) return null;
  if (typeof createdAt !== 'string' || Number.isNaN(Date.parse(createdAt))) return null;

  return {
    id: suggestionId,
    content,
    createdAt,
    pinned: false,
    ...(typeof reason === 'string' && reason.trim() ? { reason } : {}),
  };
}

export function parseSuggestion(raw: string): Suggestion | null {
  try {
    return toSuggestion(JSON.parse(raw));
  } catch {
    return null;
  }
}

/**
 * `RoomEvent.DataReceived` 한 건을 꼬리질문으로 읽는다. 아니면 null 이다.
 *
 * 같은 방에 다른 토픽의 패킷이 흐를 수 있어 토픽을 먼저 본다.
 */
export function readSuggestionPacket(payload: Uint8Array, topic?: string): Suggestion | null {
  if (topic !== SUGGESTION_TOPIC) return null;
  try {
    // fatal 로 두면 깨진 바이트가 대체 문자로 조용히 바뀌지 않고 여기서 던진다.
    return parseSuggestion(new TextDecoder('utf-8', { fatal: true }).decode(payload));
  } catch {
    return null;
  }
}
