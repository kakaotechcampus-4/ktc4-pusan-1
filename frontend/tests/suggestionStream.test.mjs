import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  parseSuggestion,
  readSuggestionPacket,
  SUGGESTION_TOPIC,
} from '../src/lib/suggestionStream.ts';

/** BE 가 보내는 모양 그대로 (`SuggestionResponse`). */
const packet = {
  suggestionId: 'sug_001',
  content: '초당 2만 건은 어떤 병목을 해결해서 나온 수치인가요?',
  evidenceUtteranceIds: ['utt_002', 'utt_001'],
  status: 'NEW',
  createdAt: '2026-10-23T05:12:30.123456Z',
};

const encode = (value) => new TextEncoder().encode(JSON.stringify(value));

test('suggestionId 를 id 로 옮기고 화면이 쓰지 않는 필드는 버린다', () => {
  assert.equal(SUGGESTION_TOPIC, 'irya.suggestion.v1');
  assert.deepEqual(parseSuggestion(JSON.stringify(packet)), {
    id: 'sug_001',
    content: packet.content,
    createdAt: packet.createdAt,
    pinned: false,
  });
});

test('서버가 어떤 모양으로 시각을 주든 받는다', () => {
  for (const createdAt of [
    '2026-10-23T05:12:30.123456Z',
    '2026-10-23T05:12:30+00:00',
    '2026-10-23T05:12:30',
  ]) {
    assert.equal(parseSuggestion(JSON.stringify({ ...packet, createdAt }))?.createdAt, createdAt);
  }
});

test('깨진 JSON 과 빈 값은 버리고 다음 정상 패킷을 받는다', () => {
  const invalid = [
    null,
    [],
    'text',
    1,
    {},
    { ...packet, suggestionId: '' },
    { ...packet, suggestionId: '  ' },
    { ...packet, suggestionId: 7 },
    // 읽을 것이 없는 질문은 자리만 차지한다.
    { ...packet, content: '' },
    { ...packet, content: '\n ' },
    { ...packet, content: null },
    { ...packet, createdAt: '어제' },
    { ...packet, createdAt: 1761196350 },
  ];
  assert.equal(parseSuggestion('{broken'), null);
  for (const value of invalid) assert.equal(parseSuggestion(JSON.stringify(value)), null);
  for (const field of ['suggestionId', 'content', 'createdAt']) {
    const incomplete = { ...packet };
    delete incomplete[field];
    assert.equal(parseSuggestion(JSON.stringify(incomplete)), null);
  }
  assert.equal(parseSuggestion(JSON.stringify(packet))?.id, 'sug_001');
});

test('우리 토픽이 아닌 패킷은 건드리지 않는다', () => {
  assert.equal(readSuggestionPacket(encode(packet), SUGGESTION_TOPIC)?.id, 'sug_001');
  for (const topic of ['irya.transcript.v1', '', 'irya.suggestion.v2', undefined]) {
    assert.equal(readSuggestionPacket(encode(packet), topic), null);
  }
});

test('한글 본문이 바이트를 거쳐도 그대로이고, 깨진 바이트는 버린다', () => {
  assert.equal(readSuggestionPacket(encode(packet), SUGGESTION_TOPIC)?.content, packet.content);
  // UTF-8 이 아닌 바이트. 대체 문자로 조용히 통과하면 안 된다.
  assert.equal(readSuggestionPacket(new Uint8Array([0xff, 0xfe, 0x00]), SUGGESTION_TOPIC), null);
});
