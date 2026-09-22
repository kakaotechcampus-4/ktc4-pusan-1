/**
 * 올리기 전에 PDF 를 살짝 들여다본다.
 *
 * 두 가지를 얻는다.
 *   쪽수      — 읽는 데 얼마나 걸릴지 안내하는 데 쓴다
 *   글자 유무 — 스캔본(이미지만 있는 PDF)을 미리 거른다
 *
 * 스캔본은 서버가 OCR 을 돌리지 않으면 "완료" 인데 내용이 빈 문서가 된다. 50MB 를 올리고
 * 몇 분 기다린 뒤에야 그걸 알게 되는 것보다, 올리기 전에 알려주는 편이 낫다.
 *
 * pdf.js 는 번들이 크므로 이 파일에서만 동적 import 한다 — 업로드 화면을 연 사람만 받는다.
 */

/** 앞쪽 몇 장만 본다. 글자가 있는 문서라면 첫 장에 이미 있다. */
const PAGES_TO_SCAN = 2;

/** 이 글자 수를 넘으면 "글자가 있는 문서" 로 본다. 표지만 이미지인 경우를 넘기기 위한 여유다. */
const TEXT_THRESHOLD = 20;

export interface PdfInfo {
  pages: number;
  /** 앞쪽 몇 장에서 글자를 찾았는가 */
  hasText: boolean;
}

export async function inspectPdf(file: File): Promise<PdfInfo | null> {
  try {
    const pdfjs = await import('pdfjs-dist');
    // 워커를 따로 띄워야 큰 문서를 열 때 화면이 멈추지 않는다.
    const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

    const doc = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;

    let text = '';
    for (let i = 1; i <= Math.min(PAGES_TO_SCAN, doc.numPages); i++) {
      const page = await doc.getPage(i);
      const content = await page.getTextContent();
      text += content.items.map((item) => ('str' in item ? item.str : '')).join('');
      if (text.trim().length > TEXT_THRESHOLD) break;
    }

    const info = { pages: doc.numPages, hasText: text.trim().length > TEXT_THRESHOLD };
    void doc.destroy();
    return info;
  } catch {
    // 암호가 걸렸거나 깨진 파일이면 여기로 온다. 검사는 어디까지나 도움말이므로
    // 실패하면 조용히 넘기고 업로드는 그대로 진행시킨다 — 판정은 서버가 한다.
    return null;
  }
}

/** 쪽수로 어림한 처리 시간 안내. 정확한 값이 아니라 기다림의 눈금이다. */
export function estimateReadTime(pages: number): string {
  if (pages <= 10) return '몇 초';
  if (pages <= 50) return '1분 이내';
  return '수 분';
}
