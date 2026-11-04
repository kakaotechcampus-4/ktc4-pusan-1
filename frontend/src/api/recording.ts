/**
 * 녹화 재생 API (#112).
 *
 * 검토 상세와 따로 부른다 — 서명 URL 이 10분 만에 만료돼서 상세와 같이 캐시해 두면
 * 화면을 다시 열 때 이미 죽은 주소가 된다.
 */

import type { Recording, RecordingResponse } from '../types/interview';
import { ApiError, request } from './client';

/**
 * 404 는 오류가 아니다.
 *
 * 명세: 「녹화가 없거나 합치지 못했으면(FAILED) 404 — 화면은 둘 다 녹화 없이 전사로
 * 검토한다.」 그래서 에러로 던지지 않고 `NONE` 으로 바꿔 화면이 전사만으로 그려지게 한다.
 * 던지면 검토 화면 전체가 오류 화면으로 바뀌어, 읽을 수 있는 문답까지 못 보게 된다.
 */
export const getRecording = async (sessionId: string): Promise<RecordingResponse> => {
  try {
    // 202 도 2xx 라 본문이 그대로 온다 (`{"status": "PROCESSING"}`).
    const body = await request<{ status: 'PROCESSING' } | Recording>(
      `/api/v1/sessions/${sessionId}/recording`,
    );
    return 'url' in body ? { status: 'READY', ...body } : body;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return { status: 'NONE' };
    throw e;
  }
};
