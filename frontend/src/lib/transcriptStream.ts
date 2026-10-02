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
