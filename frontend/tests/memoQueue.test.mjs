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

test('로그아웃 뒤 늦은 응답이 새 계정의 메모를 덮지 않는다', async () => {
  const finish = [];
  const queue = createMemoQueue(
    (id, value) => new Promise((resolve) => finish.push(() => resolve({ id, value }))),
  );
  queue.edit('a', '이전 계정');
  const old = queue.flush('a');
  queue.clear();
  queue.edit('a', '새 계정');
  const current = queue.flush('a');
  finish[0]();
  await old;
  assert.equal(queue.read('a').memo, '새 계정');
  assert.notEqual(queue.read('a').state, 'saved');
  finish[1]();
  await current;
  assert.equal(queue.read('a').result.value, '새 계정');
  queue.clear();
});

test('파일 조회 전 저장을 기다리고 실패한 메모가 있으면 중단한다', async () => {
  let finish;
  const queue = createMemoQueue(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  queue.edit('a', '파일에 담을 메모');
  let done = false;
  const reading = queue.flushForRead(['a']).then(() => {
    done = true;
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(done, false);
  finish();
  await reading;
  assert.equal(queue.read('a').state, 'saved');
  queue.clear();
  const failed = createMemoQueue(async () => {
    throw Error('offline');
  });
  failed.edit('b', '잃으면 안 되는 메모');
  await assert.rejects(failed.flushForRead(['b']), /메모를 저장하지 못했습니다/);
  failed.clear();
});

test('저장 요청은 처음 읽은 값과 직전 저장에 성공한 값을 기준으로 보낸다', async () => {
  const calls = [];
  const queue = createMemoQueue(async (id, memo, expectedMemo) => {
    calls.push({ id, memo, expectedMemo });
  });
  queue.hydrate('a', '처음 서버값');
  queue.edit('a', '첫 저장');
  await queue.flush('a');
  queue.edit('a', '둘째 저장');
  await queue.flush('a');
  assert.deepEqual(
    calls.map((call) => call.expectedMemo),
    ['처음 서버값', '첫 저장'],
  );
  queue.clear();
});

test('충돌한 입력은 자동 재시도하지 않고 서버값 확인 후 명시적으로 저장한다', async () => {
  const calls = [];
  let server = '다른 탭의 메모';
  const queue = createMemoQueue(async (id, memo, expectedMemo) => {
    calls.push(expectedMemo);
    if (server !== expectedMemo)
      throw Object.assign(new Error('conflict'), { code: 'MEMO_CONFLICT' });
    server = memo;
  });
  queue.hydrate('a', '처음 값');
  queue.edit('a', '내 입력');
  await queue.flush('a');
  assert.equal(queue.read('a').state, 'conflict');
  queue.edit('a', '계속 작성한 입력');
  await queue.flush('a');
  await queue.reapply('a');
  assert.equal(calls.length, 1);
  assert.equal(queue.read('a').memo, '계속 작성한 입력');
  await assert.rejects(queue.flushForRead(['a']), /메모를 저장하지 못했습니다/);
  queue.reviewConflict('a', server);
  await queue.reapply('a');
  assert.equal(server, '계속 작성한 입력');
  assert.equal(queue.read('a').state, 'saved');
  queue.clear();
});

test('서버 메모를 확인한 뒤 다시 바뀌면 재적용도 충돌로 남긴다', async () => {
  const queue = createMemoQueue(async () => {
    throw Object.assign(new Error(), { code: 'MEMO_CONFLICT' });
  });
  queue.hydrate('a', '이전 값');
  queue.edit('a', '내 입력');
  await queue.flush('a');
  queue.reviewConflict('a', '');
  await queue.reapply('a');
  assert.equal(queue.read('a').state, 'conflict');
  assert.equal(queue.read('a').serverMemo, undefined);
  assert.equal(queue.read('a').memo, '내 입력');
  queue.clear();
});
