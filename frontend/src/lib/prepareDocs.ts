/**
 * 업로드 직전 점검.
 *
 * 형식·용량(checkFile)만 보던 것을 한 단계 넓혔다. 서버에 보내기 전에 여기서 걸러야
 * 사용자가 50MB 를 올리고 몇 분 기다린 뒤에 실패를 알게 되는 일이 없다.
 *
 *   1. 형식·용량        확장자와 MIME
 *   2. 내용 확인        파일 앞부분이 진짜 그 형식인지
 *   3. 중복             이미 올린 문서와 내용이 같은지
 *   4. 스캔본·쪽수      PDF 안에 글자가 있는지, 몇 쪽인지
 *
 * 2~4 는 막지 않고 알려주기만 하는 항목도 있다. 판정은 서버가 한다.
 */

import { checkFile, fileFingerprint, matchesKind, type UploadableKind } from './docFile';
import { estimateReadTime, inspectPdf } from './pdfInspect';
import type { UploadRejection } from '../types/interview';

const REJECTION_MESSAGE: Record<UploadRejection, string> = {
  'unsupported-type': 'PDF 와 DOCX 만 올릴 수 있습니다.',
  'too-large': '50MB 이하 파일만 올릴 수 있습니다.',
};

export interface PreparedDoc {
  file: File;
  kind: UploadableKind;
  /** 내용 지문. 중복 판별에 쓴다. 보안 컨텍스트가 아니면 null */
  fingerprint: string | null;
  /** 올려도 되지만 알아둘 점 — 예: 스캔본 */
  warning?: string;
  /** 쪽수와 예상 시간 안내 */
  hint?: string;
}

export interface PrepareResult {
  accepted: PreparedDoc[];
  /** 올리지 않은 파일과 그 이유 */
  rejected: { name: string; message: string }[];
}

/**
 * @param existing 이미 올라간 문서들의 지문 — 중복을 걸러내는 데 쓴다
 */
export async function prepareDocs(files: File[], existing: string[]): Promise<PrepareResult> {
  const accepted: PreparedDoc[] = [];
  const rejected: PrepareResult['rejected'] = [];
  // 한 번에 여러 개를 떨어뜨렸을 때, 그 안에서의 중복도 잡아야 한다.
  const seen = new Set(existing);

  for (const file of files) {
    const checked = checkFile(file);
    if (!checked.ok) {
      rejected.push({ name: file.name, message: REJECTION_MESSAGE[checked.reason] });
      continue;
    }

    if (!(await matchesKind(file, checked.kind))) {
      rejected.push({
        name: file.name,
        message: `확장자는 ${checked.kind.toUpperCase()} 인데 내용이 다릅니다. 파일을 다시 확인해주세요.`,
      });
      continue;
    }

    const fingerprint = await fileFingerprint(file);
    if (fingerprint && seen.has(fingerprint)) {
      rejected.push({ name: file.name, message: '이미 올린 문서와 내용이 같습니다.' });
      continue;
    }
    if (fingerprint) seen.add(fingerprint);

    const prepared: PreparedDoc = { file, kind: checked.kind, fingerprint };

    if (checked.kind === 'pdf') {
      const info = await inspectPdf(file);
      if (info) {
        prepared.hint = `${info.pages}쪽 · 읽는 데 ${estimateReadTime(info.pages)}`;
        if (!info.hasText) {
          prepared.warning =
            '글자가 없는 스캔본 같습니다. 그대로 올리면 내용을 읽지 못할 수 있습니다.';
        }
      }
    }

    accepted.push(prepared);
  }

  return { accepted, rejected };
}
