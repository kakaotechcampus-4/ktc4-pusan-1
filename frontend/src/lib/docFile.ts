/**
 * 업로드 가능한 문서 판별.
 *
 * 서버에 보내기 전에 FE 가 먼저 거른다. 50MB 파일을 다 올린 뒤 거절당하면
 * 사용자가 그 시간을 통째로 낭비한다.
 */

import type { UploadRejection } from '../types/interview';

/** MIME 타입 → 문서 종류 */
const BY_MIME: Record<string, UploadableKind> = {
  'application/pdf': 'pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
};

/** 확장자 → 문서 종류. 일부 환경에서 MIME 이 비어 오는 경우를 위한 보조 수단이다. */
const BY_EXTENSION: Record<string, UploadableKind> = {
  pdf: 'pdf',
  docx: 'docx',
};

export const MAX_BYTES = 50 * 1024 * 1024;

/** `<input accept>` 에 넣는 값 */
export const ACCEPT_ATTR = '.pdf,.docx';

/** 파일로 올릴 수 있는 종류. 붙여넣은 텍스트는 업로드 경로를 타지 않는다. */
export type UploadableKind = 'pdf' | 'docx';

export type DocCheck = { ok: true; kind: UploadableKind } | { ok: false; reason: UploadRejection };

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

/* ---------------------------------------------------------------- *
 * 내용 기반 검사
 *
 * 확장자와 MIME 은 이름표일 뿐이다. 둘 다 사용자가 바꿀 수 있어서, 실제로 무엇인지는
 * 파일 앞부분을 읽어야 안다. 서버도 다시 확인하지만, 여기서 걸러야 헛된 업로드가 없다.
 * ---------------------------------------------------------------- */

/** 파일 앞부분 시그니처(매직 바이트). 붙여넣은 텍스트는 파일이 아니라 여기에 없다. */
const SIGNATURES: Record<UploadableKind, number[]> = {
  // "%PDF"
  pdf: [0x25, 0x50, 0x44, 0x46],
  // DOCX 는 ZIP 컨테이너다 — "PK\x03\x04"
  docx: [0x50, 0x4b, 0x03, 0x04],
};

/**
 * 파일 내용이 이름표와 맞는지 본다.
 *
 * 읽기에 실패하면 true 를 돌려준다. 검사는 도움말이지 관문이 아니다 —
 * 읽지 못했다는 이유로 정상 파일을 막으면 안 된다.
 */
export async function matchesKind(file: File, kind: UploadableKind): Promise<boolean> {
  const expected = SIGNATURES[kind];
  try {
    const head = new Uint8Array(await file.slice(0, expected.length).arrayBuffer());
    return expected.every((byte, i) => head[i] === byte);
  } catch {
    return true;
  }
}

/**
 * 파일 내용의 지문.
 *
 * 같은 문서를 두 번 올리는 것을 막는 데 쓴다. 이름이 달라도 내용이 같으면 같은 지문이 나온다.
 * crypto.subtle 은 보안 컨텍스트(https 또는 localhost)에서만 있으므로, 없으면 null 을 준다.
 */
export async function fileFingerprint(file: File): Promise<string | null> {
  if (!crypto?.subtle) return null;
  try {
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    return [...new Uint8Array(digest)]
      .slice(0, 8)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  } catch {
    return null;
  }
}
