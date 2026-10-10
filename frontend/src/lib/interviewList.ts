/**
 * 지원자 목록 한 줄을 읽는 규칙 (#137 1-1).
 *
 * 화면에서 빼 둔 이유는 테스트 때문이다 — 페이지는 JSX 라 `node --test` 가 못 읽는다.
 * 여기 있는 판단은 숫자 대신 무슨 말을 적을지를 정하므로 틀리면 사용자가 바로 읽는다.
 */

import type { InterviewListItem } from '../types/interview';

/**
 * 숫자 칸 대신 보여 줄 말. 집계가 있으면 null (= 숫자를 적어라).
 *
 * `counts` 는 요약이 READY 일 때만 온다. 그 전에는 셀 것이 아직 없다는 뜻이라
 * 0 을 적지 않는다 — 0 은 「세어 봤더니 없다」로 읽히기 때문이다.
 *
 * 순서가 중요하다. `interviewedAt` 을 먼저 보면, 아무도 입장하지 않고 끝낸 면접은
 * 시각이 없으므로(서버 `_timing`) 요약이 FAILED 여도 「면접 전」이라고 말하게 된다.
 * 끝났는데 안 끝났다고 하는 셈이다. 그래서 요약 상태를 먼저 본다.
 */
export function pendingReason(item: InterviewListItem): string | null {
  if (item.counts) return null;
  if (item.summaryStatus === 'FAILED') return '정리 실패';
  if (item.summaryStatus === 'PROCESSING') return '정리 중';
  // 시각이 없으면 아직 아무도 들어오지 않았다.
  if (item.interviewedAt === null) return '면접 전';
  // 시작은 했는데 길이가 없다 = 아직 끝나지 않았다 (서버가 ended_at 없으면 null 을 준다).
  if (item.durationSec === null) return '진행 중';
  // 끝났는데 요약이 아직 없다. 「정리 중」이라고 하면 돌고 있지도 않은 것을 돈다고 말한다.
  return '정리 전';
}

/**
 * 면접 길이. 알 수 없으면 null (= 「—」를 적어라).
 *
 * 1 분 미만을 「0분」으로 적지 않는다 — 「길이를 못 구했다」로 읽힌다.
 * 집계에서 0 을 피한 것과 같은 이유다.
 */
export function durationLabel(durationSec: number | null): string | null {
  if (durationSec === null) return null;
  if (durationSec < 60) return '1분 미만';
  return `${Math.round(durationSec / 60)}분`;
}
