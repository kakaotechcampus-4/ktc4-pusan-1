import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pageTitle } from '../src/lib/pageTitle.ts';

test('화면마다 다른 문서 제목을 주고 홈과 모르는 경로는 소개 제목을 쓴다', () => {
  assert.equal(pageTitle('/candidates'), '지원자 관리 | IRYA');
  assert.equal(pageTitle('/interview/ses_1/summary'), '면접 요약 | IRYA');
  assert.equal(pageTitle('/interview/ses_1'), '면접 | IRYA');
  assert.equal(pageTitle('/report/int_1'), '면접 리포트 | IRYA');
  assert.equal(pageTitle('/'), 'IRYA — 면접은 사람이, 정리는 AI가');
  assert.equal(pageTitle('/nowhere'), 'IRYA — 면접은 사람이, 정리는 AI가');
});
