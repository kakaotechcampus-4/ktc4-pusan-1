import type { TextStreamReader } from 'livekit-client';
import type { StreamEvent } from '../types/interview';

export const TRANSCRIPT_TOPIC = 'irya.transcript.v1';

/** 프레임 하나가 깨져도 통화와 다음 전사는 계속 받아야 한다. */
export function parseStreamEvent(raw: string): StreamEvent | null {
  try {
    const event: unknown = JSON.parse(raw);
    if (!event || typeof event !== 'object' || Array.isArray(event)) return null;
    const value = event as Record<string, unknown>;

    if (value.type === 'stream.degraded') {
      return typeof value.reason === 'string' ? { type: value.type, reason: value.reason } : null;
    }

    if (value.speaker !== 'INTERVIEWER' && value.speaker !== 'CANDIDATE') return null;
    if (typeof value.at !== 'number' || !Number.isFinite(value.at) || value.at < 0) return null;

    switch (value.type) {
      case 'speech.start':
      case 'speech.end':
        return { type: value.type, speaker: value.speaker, at: value.at };
      case 'transcript.delta':
        if (
          typeof value.utteranceId !== 'string' ||
          !value.utteranceId.trim() ||
          typeof value.text !== 'string' ||
          typeof value.final !== 'boolean'
        )
          return null;
        return {
          type: value.type,
          utteranceId: value.utteranceId,
          speaker: value.speaker,
          text: value.text,
          at: value.at,
          final: value.final,
        };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

/** 읽기 완료 순서가 아니라 수신 순서를 보존한다. Room마다 만들어 이전 대기를 넘기지 않는다. */
export function createTranscriptStreamHandler(
  apply: (event: StreamEvent) => void,
  isCancelled: () => boolean,
) {
  let queue = Promise.resolve();
  return (reader: Pick<TextStreamReader, 'readAll'>) => {
    // 읽기는 함께 시작하고 대기 중 실패도 바로 받는다. 뒤 조각이 먼저 닫혀도 적용 순서는 지킨다.
    const reading = reader.readAll().catch(() => null);
    queue = queue.then(async () => {
      const raw = await reading;
      if (isCancelled()) return;
      if (raw === null) {
        apply({ type: 'stream.degraded', reason: '전사를 받지 못했습니다.' });
        return;
      }
      const event = parseStreamEvent(raw);
      if (event) apply(event);
    });
    return queue;
  };
}
