import type { Speaker, StreamEvent } from '../types/interview';

/** AI Worker가 면접관에게만 보내는 LiveKit text stream topic. */
export const TRANSCRIPT_TOPIC = 'irya.transcript.v1';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isSpeaker(value: unknown): value is Speaker {
  return value === 'INTERVIEWER' || value === 'CANDIDATE';
}

/** 신뢰하지 않는 room payload를 화면의 기존 이벤트 계약으로 좁힌다. */
export function parseTranscriptEvent(raw: string): StreamEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(value) || typeof value.type !== 'string') return null;

  if (value.type === 'stream.degraded') {
    return typeof value.reason === 'string'
      ? { type: 'stream.degraded', reason: value.reason }
      : null;
  }

  if (
    value.type !== 'transcript.delta' ||
    typeof value.utteranceId !== 'string' ||
    !isSpeaker(value.speaker) ||
    typeof value.text !== 'string' ||
    typeof value.at !== 'number' ||
    !Number.isFinite(value.at) ||
    value.at < 0 ||
    typeof value.final !== 'boolean'
  ) {
    return null;
  }

  return {
    type: 'transcript.delta',
    utteranceId: value.utteranceId,
    speaker: value.speaker,
    text: value.text,
    at: value.at,
    final: value.final,
  };
}
