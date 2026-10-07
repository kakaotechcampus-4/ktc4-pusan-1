/**
 * 면접 기록 API (S3).
 *
 * 실제 BE 는 끝난 면접이면 READY(새 모양, #163)를, 준비 전이면 202 PROCESSING 을 준다.
 * 화면은 아직 옛 READY 모양이라 `lib/reviewCompat.ts` 가 옮겨 받는다.
 */

import { toLegacyReview, type ReviewReadyBody } from '../lib/reviewCompat';
import type { ReviewResponse } from '../types/interview';
import { request } from './client';

// 준비 전 응답은 202 다. request() 는 2xx 를 모두 성공으로 보고 본문을 넘기므로
// PROCESSING 도 에러가 아니라 데이터로 받는다.
//
// 실제 BE 의 READY 는 새 모양(#163)이라 지금 화면이 그리는 모양으로 옮겨 받는다.
// 개발용 목(`mocks/mockApi.ts`)은 아직 옛 모양을 돌려주므로 그대로 둔다.
export const getReview = async (interviewId: string): Promise<ReviewResponse> => {
  const body = await request<ReviewResponse | ReviewReadyBody>(
    `/api/v1/interviews/${interviewId}/review`,
  );
  return 'summaryStatus' in body ? toLegacyReview(body) : body;
};
