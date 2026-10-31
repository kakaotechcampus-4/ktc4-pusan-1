import assert from 'node:assert/strict';
import { test } from 'node:test';
import { toTranscriptSec, toVideoSec } from '../src/lib/recordingTime.ts';

test('녹화가 전사보다 늦게 열린 만큼 당겨서 재생한다', () => {
  // 녹화가 전사 원점보다 2.5초 뒤에 시작했다 → 전사 15초 장면은 녹화 12.5초
  assert.equal(toVideoSec(15, 2500), 12.5);
  assert.equal(toVideoSec(0, 0), 0);
});

test('녹화가 그 장면보다 늦게 시작했으면 맨 앞을 보여준다', () => {
  // 음수를 currentTime 에 넣으면 브라우저가 무시해 재생 위치가 엉뚱한 곳에 남는다.
  assert.equal(toVideoSec(1, 5000), 0);
});

test('오프셋이 음수여도(녹화가 먼저 열렸어도) 뒤로 민다', () => {
  // 명세가 방향만 정하고 부호를 제한하지 않는다. 식을 그대로 따른다.
  assert.equal(toVideoSec(10, -2000), 12);
});

test('되돌리면 원래 전사 시각이 나온다', () => {
  const offsetMs = 2500;
  assert.equal(toTranscriptSec(toVideoSec(15, offsetMs), offsetMs), 15);
});
