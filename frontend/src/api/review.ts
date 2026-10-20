/**
 * 면접 기록 API.
 *
 * 끝난 면접이면 READY, 준비 전이면 202 PROCESSING 이다. 202 도 2xx 라
 * `request()` 가 본문을 그대로 넘기므로 오류가 아니라 데이터로 받는다.
 */

import type { ReviewResponse } from '../types/interview';
import { request } from './client';

export const getReview = (interviewId: string): Promise<ReviewResponse> =>
  request<ReviewResponse>(`/api/v1/interviews/${interviewId}/review`);
