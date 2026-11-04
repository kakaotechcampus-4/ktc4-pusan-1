import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DELETE_FAILURE_MESSAGE, deleteFailure } from '../src/lib/interviewDelete.ts';

test('이미 없는 면접은 실패로 다루지 않는다', () => {
  // 지운 것과 결과가 같다. 목록만 맞추면 되는 일이라 오류 문구를 띄우지 않는다.
  assert.equal(deleteFailure(404), 'gone');
});

test('진행 중과 로그인 풀림은 할 일이 다르다', () => {
  assert.equal(deleteFailure(409), 'busy');
  assert.equal(deleteFailure(401), 'signed-out');
  // 로그인이 풀린 것은 기다려서 되는 일이 아니다 (#150).
  assert.ok(!DELETE_FAILURE_MESSAGE['signed-out'].includes('잠시 후'));
  assert.ok(DELETE_FAILURE_MESSAGE.failed.includes('잠시 후'));
});

test('모르는 코드와 응답 없음은 다시 시도로 보낸다', () => {
  for (const status of [400, 403, 500, 502, 0, undefined])
    assert.equal(deleteFailure(status), 'failed');
});

test('모든 이유에 문구가 있다', () => {
  for (const failure of ['gone', 'busy', 'signed-out', 'failed'])
    assert.ok(DELETE_FAILURE_MESSAGE[failure].length > 0, failure);
});
