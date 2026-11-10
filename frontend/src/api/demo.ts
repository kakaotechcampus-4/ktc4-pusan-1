/**
 * 발표 데모용 발화 주입 — `POST /sessions/{sessionId}/demo/utterance`.
 *
 * 제품 기능이 아니다. 무대에서 면접관이 키를 누르면 준비한 지원자 답변이 이 경로로
 * 들어가고, BE 가 그것을 Agent 에 보내 **지원자 발화**로 파이프라인에 넣는다. 자막 ·
 * 발화 저장 · 꼬리질문 생성은 그 뒤 전부 실제 경로다.
 *
 * 404 는 서버에서 데모가 꺼져 있거나 **이 세션이 허용 목록에 없는** 것이고
 * (`DEMO_INJECTION_ENABLED` · `DEMO_INJECTION_SESSIONS`), 503 은 LiveKit 방에
 * 전달하지 못한 것이다. 무대에서 할 수 있는 일이 다르지만 둘 다 그 자리에서
 * 손쓸 수 없어서, 부르는 쪽은 콘솔에만 남기고 화면은 건드리지 않는다.
 */

import { request } from './client';

export const injectDemoUtterance = (sessionId: string, content: string): Promise<void> =>
  request<void>(`/api/v1/sessions/${sessionId}/demo/utterance`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
