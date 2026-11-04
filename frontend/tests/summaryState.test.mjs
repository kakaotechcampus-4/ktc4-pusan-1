import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  failureMessage,
  LATE_POLL_LIMIT,
  LATE_POLL_MS,
  latePollInterval,
} from '../src/lib/summaryState.ts';

test('대화가 없었던 실패는 다시 묻지 않는다 — 기다려도 안 바뀐다', () => {
  assert.equal(latePollInterval('NO_TRANSCRIPT', 1), false);
});

test('그 밖의 실패는 늦은 결과를 한동안 기다린다', () => {
  assert.equal(latePollInterval(null, 1), LATE_POLL_MS);
  assert.equal(latePollInterval(undefined, LATE_POLL_LIMIT - 1), LATE_POLL_MS);
  assert.equal(latePollInterval(null, LATE_POLL_LIMIT), false);
});

test('안내는 까닭과 기다리는 중인지에 따라 다르다', () => {
  assert.match(failureMessage('NO_TRANSCRIPT', false).title, /대화가 기록되지/);
  assert.match(failureMessage(null, true).title, /늦어지고/);
  assert.match(failureMessage(null, false).title, /만들지 못했/);
});
