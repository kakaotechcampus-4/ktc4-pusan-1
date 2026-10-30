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
  writeMemoDraft(key, '서버 저장 전 한글 초안');
  assert.equal(readMemoDraft(key), '서버 저장 전 한글 초안');
  assert.equal(readMemoDraft(memoDraftKey('owner2', 'interview1')), null);
  assert.equal(readMemoDraft(memoDraftKey('owner1', 'interview2')), null);
  values.unrelated = '유지';
  clearMemoDrafts();
  assert.equal(readMemoDraft(key), null);
  assert.equal(values.unrelated, '유지');
  delete globalThis.sessionStorage;
  assert.doesNotThrow(() => writeMemoDraft(key, '저장소 차단'));
  assert.equal(readMemoDraft(key), null);
});
