/**
 * 면접 기록 API (S3).
 *
 * ⚠️ BE 명세에 없는 엔드포인트다. 목으로만 동작한다.
 */

import type { ReviewResponse } from '../types/interview';
import { request } from './client';

// 준비 전 응답은 202 다. request() 는 2xx 를 모두 성공으로 보고 본문을 넘기므로
// PROCESSING 도 에러가 아니라 데이터로 받는다.
export const getReview = (interviewId: string) =>
  request<ReviewResponse>(`/api/v1/interviews/${interviewId}/review`);
