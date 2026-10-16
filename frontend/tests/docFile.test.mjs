import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkFile, MAX_BYTES, parseContextDoc } from '../src/lib/docFile.ts';

test('서버와 같은 확장자 기준으로 PDF 만 받고 DOCX · 빈 파일 · 크기 초과를 거절한다', () => {
  const file = { name: 'sample.PDF', type: '', size: MAX_BYTES };
  assert.deepEqual(checkFile(file), { ok: true, kind: 'pdf' });
  assert.deepEqual(checkFile({ ...file, name: '.pdf' }), { ok: true, kind: 'pdf' });
  // DOCX 는 본문을 뽑지 못해 올리는 쪽에서 막혔다 (#149). MIME 이 뭐라고 하든 확장자로 거른다.
  assert.deepEqual(checkFile({ ...file, name: 'sample.docx', type: 'application/pdf' }), {
    ok: false,
    reason: 'unsupported-type',
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
    assert.deepEqual(parseContextDoc(JSON.stringify({ ...doc, status })), {
      ...doc,
      status,
      category: null,
    });
});

test('읽는 쪽은 전에 올라온 DOCX 를 살리고 모르는 분류만 떨어뜨린다', () => {
  const doc = { id: 'doc_1', name: 'sample.docx', kind: 'docx', sizeBytes: 4, status: 'ready' };
  // 올리는 길은 막혔어도 조회 응답에는 남아 있다. 여기서 null 로 만들면 목록에서 사라진다.
  assert.deepEqual(parseContextDoc(JSON.stringify(doc)), { ...doc, category: null });
  for (const category of ['jd', 'internal'])
    assert.deepEqual(parseContextDoc(JSON.stringify({ ...doc, category })), { ...doc, category });
  // 분류를 못 읽어도 문서는 남긴다 — 칸만 잃고 파일은 보인다.
  for (const category of ['resume', '', 7, null])
    assert.deepEqual(parseContextDoc(JSON.stringify({ ...doc, category })), {
      ...doc,
      category: null,
    });
});
