import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkFile, MAX_BYTES, parseContextDoc } from '../src/lib/docFile.ts';

test('서버와 같은 확장자 기준으로 PDF·DOCX를 받고 빈 파일과 크기 초과를 거절한다', () => {
  const file = { name: 'sample.PDF', type: '', size: MAX_BYTES };
  assert.deepEqual(checkFile(file), { ok: true, kind: 'pdf' });
  assert.deepEqual(checkFile({ ...file, name: '.pdf' }), { ok: true, kind: 'pdf' });
  assert.deepEqual(checkFile({ ...file, name: 'sample.docx', type: 'text/plain' }), {
    ok: true,
    kind: 'docx',
  });
  for (const name of ['sample.txt', 'sample', 'pdf'])
    assert.deepEqual(checkFile({ ...file, name, type: 'application/pdf' }), {
      ok: false,
      reason: 'unsupported-type',
    });
  assert.deepEqual(checkFile({ ...file, size: 0 }), { ok: false, reason: 'empty-file' });
  assert.deepEqual(checkFile({ ...file, size: MAX_BYTES + 1 }), { ok: false, reason: 'too-large' });
});

test('잘못된 업로드 응답은 문서가 되지 않고 다음 정상 응답은 읽힌다', () => {
  const doc = { id: 'doc_1', name: 'sample.pdf', kind: 'pdf', sizeBytes: 4, status: 'ready' };
  for (const raw of [
    '<html>error</html>',
    'null',
    '[]',
    '{}',
    JSON.stringify({ ...doc, id: '' }),
    JSON.stringify({ ...doc, status: 'uploading' }),
    JSON.stringify({ ...doc, sizeBytes: -1 }),
  ])
    assert.equal(parseContextDoc(raw), null);
  for (const status of ['ready', 'parsing', 'failed'])
    assert.deepEqual(parseContextDoc(JSON.stringify({ ...doc, status })), { ...doc, status });
});
