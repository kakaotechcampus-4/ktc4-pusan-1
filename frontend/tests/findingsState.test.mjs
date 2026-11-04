import assert from 'node:assert/strict';
import { test } from 'node:test';
import { coverageLabel, progressNote } from '../src/lib/findingsState.ts';

test('만들지 못한 면접의 역량은 「없음」이 아니라 「확인 불가」다', () => {
  assert.equal(coverageLabel('MISSING', 'FAILED'), '확인 불가');
  assert.equal(coverageLabel('MISSING', 'EMPTY'), '없음');
  assert.equal(coverageLabel('CONFIRMED', 'FAILED'), '확인');
});

test('만들지 못했으면 「모두 판단했습니다」를 말하지 않는다', () => {
  assert.equal(progressNote(0, 'FAILED'), null);
  assert.equal(progressNote(0, 'EMPTY'), '모두 판단했습니다');
  assert.equal(progressNote(2, 'COMPLETED'), '2건이 아직 판단 전입니다');
});
