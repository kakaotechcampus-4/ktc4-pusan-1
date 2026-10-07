/**
 * 검토 상세의 새 응답(#137 1-2 · #163)을 지금 면접 기록 화면이 그리는 옛 모양으로 옮긴다.
 *
 * BE 가 READY 를 내기 시작했는데 화면은 아직 옛 모양(`recording.hlsUrl` 필수,
 * `aiReview.paragraphs`)을 기대한다. 그대로 두면 끝난 면접의 기록 화면이 TypeError 로
 * 깨진다. 검토 화면을 새 응답(coverage · findings · 채택 · 북마크 · 녹화 API)으로
 * 옮기는 FE 작업 전까지의 다리다 — 그때 이 파일을 지운다.
 */

import type { Moment, Review } from '../types/interview';
// 확장자를 붙인다 — `npm test` 가 이 파일을 node 로 바로 돌린다(빌드는 tsconfig 가 허용).
import { FALLBACK_CANDIDATE } from './candidateName.ts';

/** BE 가 지금 내는 READY 응답 가운데 옛 화면이 쓰는 부분 */
export interface ReviewReadyBody {
  status: 'READY';
  /** 새 응답에만 있다. 옛 모양(개발용 목)과 가르는 데 쓴다. */
  summaryStatus: 'READY' | 'FAILED';
  interviewId: string;
  candidate: { name: string | null; role: string };
  durationSec: number | null;
  /** 요약이 FAILED 면 null 이다 */
  summary: { overview: string; keyPoints: string[] } | null;
  moments: Moment[];
}

export const toLegacyReview = (body: ReviewReadyBody): { status: 'READY' } & Review => ({
  status: 'READY',
  interviewId: body.interviewId,
  candidate: { name: body.candidate.name ?? FALLBACK_CANDIDATE, role: body.candidate.role },
  durationSec: body.durationSec ?? 0,
  // 녹화는 상세에 실리지 않는다. 녹화 API 로 받는 건 FE 전환 작업이다.
  recording: null,
  moments: body.moments,
  aiReview: { paragraphs: body.summary ? [body.summary.overview] : [] },
});
