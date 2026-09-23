/**
 * 이력서 업로드 목.
 *
 * ⚠️ BE 명세에 이력서 엔드포인트가 없다. 화면 흐름을 끊지 않기 위한 임시 코드다.
 *
 * mockApi.ts 의 경로 매칭에 얹지 못한다 — 업로드는 진행률 때문에 XHR 을 쓰고,
 * XHR 은 api/client.ts 의 request() 를 거치지 않는다. 그래서 api/resume.ts 가
 * 이 함수를 직접 부른다 (컨텍스트 문서의 handleMockUpload 와 같은 구조다).
 *
 * BE 연동 시 이 파일과 api/resume.ts 의 분기를 함께 지운다.
 */

import type { ContextDoc } from '../types/interview';

/** 실제 업로드처럼 보이도록 진행률을 나눠 올린다. 진행 표시가 실제로 움직여야 한다. */
const STEPS = 10;
const STEP_MS = 120;

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function handleMockResumeUpload(
  file: File,
  onProgress: (ratio: number) => void,
): Promise<ContextDoc> {
  for (let i = 1; i <= STEPS; i++) {
    await delay(STEP_MS);
    onProgress(i / STEPS);
  }

  return {
    id: `resume_${Date.now()}`,
    name: file.name,
    kind: file.name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'docx',
    sizeBytes: file.size,
    // 목은 파싱을 흉내내지 않는다 — 이 화면은 파싱 결과를 보여주지 않는다.
    status: 'ready',
  };
}
