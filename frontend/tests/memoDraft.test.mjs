import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  memoDraftKey,
  readMemoDraft,
  writeMemoDraft,
  clearMemoDrafts,
} from '../src/lib/memoDraft.ts';

test('탭 초안은 계정과 면접별로 구분하고 계정 전환에서 메모만 지운다', () => {
  const values = {};
  globalThis.sessionStorage = values;
  Object.defineProperties(values, {
    getItem: { value: (key) => values[key] ?? null },
    setItem: {
      value: (key, value) => {
        values[key] = value;
      },
    },
    removeItem: {
      value: (key) => {
        delete values[key];
      },
    },
  });
  const key = memoDraftKey('owner1', 'interview1');
  const draft = { memo: '서버 저장 전 한글 초안', baseline: '서버 기준값' };
  writeMemoDraft(key, draft);
  assert.deepEqual(readMemoDraft(key), draft);
  values[key] = '기존 본문 초안';
  assert.deepEqual(readMemoDraft(key), { memo: '기존 본문 초안' });
  values[key] = '{"memo":"사용자가 쓴 JSON 메모"}';
  assert.deepEqual(readMemoDraft(key), { memo: values[key] });
  writeMemoDraft(key, { memo: '기준을 모르는 초안' });
  assert.deepEqual(readMemoDraft(key), { memo: '기준을 모르는 초안', baseline: undefined });
  assert.equal(readMemoDraft(memoDraftKey('owner2', 'interview1')), null);
  assert.equal(readMemoDraft(memoDraftKey('owner1', 'interview2')), null);
  values.unrelated = '유지';
  clearMemoDrafts();
  assert.equal(readMemoDraft(key), null);
  assert.equal(values.unrelated, '유지');
  delete globalThis.sessionStorage;
  assert.doesNotThrow(() => writeMemoDraft(key, draft));
  assert.equal(readMemoDraft(key), null);
});
