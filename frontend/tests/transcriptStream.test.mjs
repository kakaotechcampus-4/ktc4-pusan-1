import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  parseStreamEvent,
  TRANSCRIPT_TOPIC,
  createTranscriptStreamHandler,
} from '../src/lib/transcriptStream.ts';

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

test('뒤 스트림이 먼저 닫혀도 조각과 final은 수신 순서대로 전달한다', async () => {
  const received = [];
  const handler = createTranscriptStreamHandler(
    (event) => received.push(event),
    () => false,
  );
  let finish;
  const first = handler({
    readAll: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  const second = handler({
    readAll: async () => JSON.stringify({ ...delta, text: '둘', final: true }),
  });
  await Promise.resolve();
  assert.equal(received.length, 0);
  finish(JSON.stringify({ ...delta, text: '첫', final: false }));
  await Promise.all([first, second]);
  assert.deepEqual(
    received.map((event) => [event.text, event.final]),
    [
      ['첫', false],
      ['둘', true],
    ],
  );
});

test('읽기 실패와 깨진 프레임 뒤에도 다음 정상 자막을 전달한다', async () => {
  const received = [];
  const handler = createTranscriptStreamHandler(
    (event) => received.push(event),
    () => false,
  );
  await handler({
    readAll: async () => {
      throw new Error('stream closed');
    },
  });
  await handler({ readAll: async () => '{broken' });
  await handler({ readAll: async () => JSON.stringify(delta) });
  assert.equal(received[0].type, 'stream.degraded');
  assert.deepEqual(received.slice(1), [delta]);
});

test('이탈 중 닫힌 스트림은 새 Room으로 넘기지 않는다', async () => {
  const received = [];
  let cancelled = false;
  let finish;
  const oldRoom = createTranscriptStreamHandler(
    (event) => received.push(event),
    () => cancelled,
  );
  const pending = oldRoom({
    readAll: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  cancelled = true;
  finish(JSON.stringify(delta));
  await pending;
  await oldRoom({
    readAll: async () => {
      throw new Error('closed');
    },
  });
  assert.deepEqual(received, []);
  const newRoom = createTranscriptStreamHandler(
    (event) => received.push(event),
    () => false,
  );
  await newRoom({ readAll: async () => JSON.stringify(delta) });
  assert.deepEqual(received, [delta]);
});
