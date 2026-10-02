import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fmt } from '../src/lib/format.ts';

test('STT의 소수 초는 mm:ss로 표시한다', () => {
  assert.equal(fmt(1.2), '00:01');
  assert.equal(fmt(12.3), '00:12');
  assert.equal(fmt(60.9), '01:00');
  assert.equal(fmt(125), '02:05');
});
