/**
 * 업로드 가능한 문서 판별.
 *
 * 서버에 보내기 전에 FE 가 먼저 거른다. 50MB 파일을 다 올린 뒤 거절당하면
 * 사용자가 그 시간을 통째로 낭비한다.
 */

import type { ContextDoc, DocKind, UploadRejection } from '../types/interview';

/**
 * BE도 파일 확장자로 판별한다. MIME만 믿으면 .txt가 업로드 단계에서 거절된다.
 *
 * **PDF 만 받는다** (#149). 본문을 뽑는 Helpy Document Vision 이 DOCX 를 읽지 못해서,
 * 올려 두기만 하면 AI 가 쓰지 못하는 문서가 된다. 서버도 `.pdf` 외에는 415 다.
 */
const BY_EXTENSION: Record<string, DocKind> = {
  pdf: 'pdf',
};

export const MAX_BYTES = 50 * 1024 * 1024;

/** `<input accept>` 에 넣는 값 */
export const ACCEPT_ATTR = '.pdf';

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
      // 이력서는 칸이 없어 null 로 온다.
      //
      // 컨텍스트 문서에 모르는 값이 오면 분류를 잃고 두 칸(JD · 사내 자료) 어디에도
      // 안 보인다 — 지울 수도 없다. 여기서 internal 로 떨어뜨리면 이력서가 사내
      // 자료 칸에 섞이므로 그러지 않는다. 서버가 `category NOT NULL DEFAULT 'internal'`
      // 로 막고 있어 오늘은 도달하지 않는다. DocCategory 에 값을 더하면 화면도 같이 늘려야 한다.
      category: doc.category === 'jd' || doc.category === 'internal' ? doc.category : null,
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
