import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  safeLoginReturnTo,
  rememberLoginReturnTo,
  readLoginReturnTo,
  consumeLoginReturnTo,
  clearLoginReturnTo,
} from '../src/lib/loginReturnTo.ts';
const origin = 'http://localhost:8080';

test('로그인 복귀는 쿼리·해시를 보존하고 외부 주소와 콜백 순환을 막는다', () => {
  const path = '/interview/ses_1?role=interviewer#devices';
  assert.equal(safeLoginReturnTo(path, origin), path);
  for (const value of [
    null,
    {},
    '',
    'https://example.com',
    '//example.com',
    '/\\example.com',
    '/a\\b',
    '/login',
    '/LOGIN/',
    '/login/',
    '/OAUTH/KAKAO/CALLBACK',
    '/login?next=/',
    '/oauth/kakao/callback',
    '/\n/example.com',
  ])
    assert.equal(safeLoginReturnTo(value, origin), '/');
});

test('탭에 보관한 목적지는 성공 뒤 한 번 소비하며 로그아웃 정리 후 남지 않는다', () => {
  const values = new Map();
  globalThis.window = { location: { origin } };
  globalThis.sessionStorage = {
    setItem: (k, v) => values.set(k, v),
    getItem: (k) => values.get(k) ?? null,
    removeItem: (k) => values.delete(k),
  };
  rememberLoginReturnTo('/settings/context');
  assert.equal(readLoginReturnTo(), '/settings/context');
  assert.equal(consumeLoginReturnTo(), '/settings/context');
  assert.equal(consumeLoginReturnTo(), '/');
  rememberLoginReturnTo('/review/int_1');
  clearLoginReturnTo();
  assert.equal(readLoginReturnTo(), '/');
  delete globalThis.window;
  delete globalThis.sessionStorage;
});
