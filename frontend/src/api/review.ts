/**
 * 면접 기록 API.
 *
 * 끝난 면접이면 READY, 준비 전이면 202 PROCESSING 이다. 202 도 2xx 라
 * `request()` 가 본문을 그대로 넘기므로 오류가 아니라 데이터로 받는다.
 */

import type {
  MarkResponse,
  MarkUpdate,
  ReviewResponse,
  ReviewUpdate,
  ReviewUpdateResponse,
} from '../types/interview';
import { request } from './client';

export const getReview = (interviewId: string): Promise<ReviewResponse> =>
  request<ReviewResponse>(`/api/v1/interviews/${interviewId}/review`);

/** 검토 상태 · 메모. 면접 단위라 AI 결과가 없어도 된다. */
export const updateReview = (interviewId: string, body: ReviewUpdate) =>
  request<ReviewUpdateResponse>(`/api/v1/interviews/${interviewId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });

/** 검토 항목의 채택 · 반려, 문답의 북마크. `itemId` 는 지금 상세의 id 여야 한다. */
export const putMark = (interviewId: string, itemId: string, body: MarkUpdate) =>
  request<MarkResponse>(`/api/v1/interviews/${interviewId}/review/marks/${itemId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
