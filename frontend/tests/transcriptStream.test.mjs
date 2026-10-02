import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseStreamEvent, TRANSCRIPT_TOPIC } from '../src/lib/transcriptStream.ts';

const delta = {
  type: 'transcript.delta',
  utteranceId: 'utterance-1',
  speaker: 'CANDIDATE',
  text: '답변입니다',
  at: 12.3,
  final: true,
};

test('워커의 delta와 네 가지 이벤트를 받는다', () => {
  assert.equal(TRANSCRIPT_TOPIC, 'irya.transcript.v1');
  for (const event of [
    delta,
    { ...delta, final: false, text: '' },
    { type: 'speech.start', speaker: 'INTERVIEWER', at: 0 },
    { type: 'speech.end', speaker: 'CANDIDATE', at: 2 },
    { type: 'stream.degraded', reason: 'STT 연결 중단' },
  ]) {
    assert.deepEqual(parseStreamEvent(JSON.stringify(event)), event);
  }
});

test('깨진 JSON과 잘못된 필드는 버리고 다음 정상 프레임을 받는다', () => {
  const invalid = [
    null,
    [],
    'text',
    1,
    {},
    { ...delta, type: 'unknown' },
    { ...delta, speaker: 'candidate' },
    { ...delta, at: -1 },
    { ...delta, at: '12' },
    { ...delta, final: 1 },
    { ...delta, text: null },
    { ...delta, utteranceId: ' ' },
    { type: 'stream.degraded', reason: 3 },
  ];
  assert.equal(parseStreamEvent('{broken'), null);
  assert.equal(parseStreamEvent('{"type":"speech.start","speaker":"CANDIDATE","at":1e999}'), null);
  for (const value of invalid) assert.equal(parseStreamEvent(JSON.stringify(value)), null);
  for (const field of ['utteranceId', 'speaker', 'text', 'at', 'final']) {
    const incomplete = { ...delta };
    delete incomplete[field];
    assert.equal(parseStreamEvent(JSON.stringify(incomplete)), null);
  }
  assert.deepEqual(parseStreamEvent(JSON.stringify(delta)), delta);
});
