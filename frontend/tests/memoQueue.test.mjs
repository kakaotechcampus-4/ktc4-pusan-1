import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createMemoQueue } from '../src/lib/memoQueue.ts';

test('저장 중 입력한 최신 값은 이전 요청이 끝난 뒤 같은 면접에 저장한다', async () => {
  const calls = [];
  const finish = [];
  const queue = createMemoQueue(
    (id, value) =>
      new Promise((resolve) => {
        calls.push([id, value]);
        finish.push(resolve);
      }),
  );
  queue.hydrate('a', '원문');
  queue.edit('a', '첫 입력');
  const saving = queue.flush('a');
  queue.edit('a', '최신 입력');
  assert.deepEqual(calls, [['a', '첫 입력']]);
  finish.shift()();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, [
    ['a', '첫 입력'],
    ['a', '최신 입력'],
  ]);
  finish.shift()();
  await saving;
  assert.equal(queue.read('a').memo, '최신 입력');
  assert.equal(queue.read('a').state, 'saved');
  queue.clear();
});
test('다른 면접과 실패한 입력을 섞지 않고 재조회가 미저장 값을 덮지 않는다', async () => {
  let fail = true;
  const calls = [];
  const queue = createMemoQueue(async (id, value) => {
    if (fail) throw Error('offline');
    calls.push([id, value]);
  });
  queue.edit('a', '남길 입력');
  await queue.flush('a');
  queue.hydrate('a', '오래된 서버값');
  assert.equal(queue.read('a').memo, '남길 입력');
  assert.equal(queue.read('a').state, 'failed');
  queue.hydrate('b', '다른 사람');
  assert.equal(queue.read('b').memo, '다른 사람');
  fail = false;
  await queue.flush('a');
  assert.deepEqual(calls, [['a', '남길 입력']]);
  queue.clear();
});
