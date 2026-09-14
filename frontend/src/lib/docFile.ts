/**
 * 업로드 가능한 문서 판별.
 *
 * 서버에 보내기 전에 FE 가 먼저 거른다. 50MB 파일을 다 올린 뒤 거절당하면
 * 사용자가 그 시간을 통째로 낭비한다.
 */

import type { DocKind, UploadRejection } from '../types/interview';

/** MIME 타입 → 문서 종류 */
const BY_MIME: Record<string, DocKind> = {
  'application/pdf': 'pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
};

/** 확장자 → 문서 종류. 일부 환경에서 MIME 이 비어 오는 경우를 위한 보조 수단이다. */
const BY_EXTENSION: Record<string, DocKind> = {
  pdf: 'pdf',
  docx: 'docx',
};

export const MAX_BYTES = 50 * 1024 * 1024;

/** `<input accept>` 에 넣는 값 */
export const ACCEPT_ATTR = '.pdf,.docx';

export type DocCheck = { ok: true; kind: DocKind } | { ok: false; reason: UploadRejection };

export function checkFile(file: File): DocCheck {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  const kind = BY_MIME[file.type] ?? BY_EXTENSION[extension];

  if (!kind) return { ok: false, reason: 'unsupported-type' };
  if (file.size > MAX_BYTES) return { ok: false, reason: 'too-large' };
  return { ok: true, kind };
}

/** 사람이 읽는 크기 */
export const fmtSize = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)}MB`
    : `${Math.max(1, Math.round(bytes / 1024))}KB`;
