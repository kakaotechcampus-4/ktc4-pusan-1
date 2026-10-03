/**
 * 업로드 가능한 문서 판별.
 *
 * 서버에 보내기 전에 FE 가 먼저 거른다. 50MB 파일을 다 올린 뒤 거절당하면
 * 사용자가 그 시간을 통째로 낭비한다.
 */

import type { ContextDoc, DocKind, UploadRejection } from '../types/interview';

/** BE도 파일 확장자로 판별한다. MIME만 믿으면 .txt가 업로드 단계에서 거절된다. */
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
  const kind = file.name.includes('.') ? BY_EXTENSION[extension] : undefined;

  if (!kind) return { ok: false, reason: 'unsupported-type' };
  if (file.size === 0) return { ok: false, reason: 'empty-file' };
  if (file.size > MAX_BYTES) return { ok: false, reason: 'too-large' };
  return { ok: true, kind };
}

/** 잘못된 응답이 업로드 진행 상태나 문서 목록을 깨뜨리지 않게 경계에서 확인한다. */
export function parseContextDoc(raw: string): ContextDoc | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const doc = value as Record<string, unknown>;
    if (typeof doc.id !== 'string' || !doc.id || typeof doc.name !== 'string') return null;
    if (doc.kind !== 'pdf' && doc.kind !== 'docx') return null;
    if (
      typeof doc.sizeBytes !== 'number' ||
      !Number.isSafeInteger(doc.sizeBytes) ||
      doc.sizeBytes < 0
    )
      return null;
    if (doc.status !== 'ready' && doc.status !== 'parsing' && doc.status !== 'failed') return null;
    return {
      id: doc.id,
      name: doc.name,
      kind: doc.kind,
      sizeBytes: doc.sizeBytes,
      status: doc.status,
    };
  } catch {
    return null;
  }
}

/** 사람이 읽는 크기 */
export const fmtSize = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)}MB`
    : `${Math.max(1, Math.round(bytes / 1024))}KB`;
