/**
 * 꼬리질문 조회 (#212).
 *
 * 면접 중에는 LiveKit 데이터 패킷으로 바로 온다. 이 API 는 입장 · 재연결 · 종료 뒤에
 * 그 전 것을 채우는 용도다. 전달에 실패한 꼬리질문을 BE 가 다시 보내지 않으므로,
 * 끊긴 사이에 온 것은 이 호출로만 되살아난다.
 *
 * 면접 주인만 부를 수 있다 — 지원자가 부르면 401 이다. 역할 분기는 부르는 쪽에서 한다.
 */

import type { Suggestion } from '../types/interview';
import { toSuggestion } from '../lib/suggestionStream';
import { request } from './client';

export const listSuggestions = async (sessionId: string): Promise<Suggestion[]> => {
  const body = await request<{ items: unknown[] }>(`/api/v1/sessions/${sessionId}/suggestions`);
  // 모양이 틀린 항목은 버린다. 하나 때문에 목록 전체를 못 그리면 면접 중에 더 손해다.
  return (body.items ?? []).map(toSuggestion).filter((s): s is Suggestion => s !== null);
};
