import assert from 'node:assert/strict';
import { test } from 'node:test';
import { consentRequest, readConsent } from '../src/lib/consentContract.ts';

const at = '2026-10-30T15:00:00+09:00';
test('#255 계약의 요청과 동의 시각을 읽고 없는 버전을 만들지 않는다', () => {
  assert.deepEqual(consentRequest({ consentedAt: null }, '2026-10-30'), {
    policyVersion: '2026-10-30',
  });
  assert.equal(readConsent({ consentedAt: null }), null);
  assert.deepEqual(readConsent({ consentedAt: at }), { agreedAt: at, version: null });
  assert.deepEqual(readConsent({ consentedAt: at, policyVersion: '2026-10-30' }), {
    agreedAt: at,
    version: '2026-10-30',
  });
});
test('#256 계약과 미구현·잘못된 응답을 구분한다', () => {
  assert.deepEqual(consentRequest({ consent: null }, '2026-10-30'), { version: '2026-10-30' });
  assert.equal(readConsent({ consent: null }), null);
  const consent = { agreedAt: at, version: '2026-10-30' };
  assert.deepEqual(readConsent({ consent }), consent);
  assert.deepEqual(readConsent(consent), consent);
  assert.throws(() => consentRequest({}, '2026-10-30'));
  assert.equal(readConsent({ agreedAt: 'broken', version: '2026-10-30' }), null);
});
