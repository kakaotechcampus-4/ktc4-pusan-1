/**
 * 면접 요약이 실패로 보일 때 무엇을 말하고, 언제까지 다시 물을지.
 *
 * 서버의 FAILED 는 두 가지다.
 *   - 요약할 대화가 없었다(`failureReason: NO_TRANSCRIPT`) — 기다려도 안 바뀐다.
 *   - 시간 한도를 넘겼거나 분석이 실패했다(`null`) — Agent 의 결과가 늦게 와도 서버가
 *     받아 READY 로 되살린다. 그래서 한동안은 천천히 다시 묻고, 「늦어진다」고 말한다.
 *
 * 화면(요약 · 면접 기록)에서 빼 둔 이유는 테스트 때문이다 — 페이지는 JSX 라
 * `node --test` 가 못 읽는다.
 */

import type { SummaryFailureReason } from '../types/interview';

/** 실패로 보인 뒤 다시 묻는 간격 */
export const LATE_POLL_MS = 15_000;
/** 실패로 보인 뒤 다시 묻는 횟수 — 약 10분. 서버 한도(기본 10분)를 한 번 더 기다린다 */
export const LATE_POLL_LIMIT = 40;

/** 늦은 결과를 기다릴 만한 실패인가 */
export const mayStillArrive = (reason: SummaryFailureReason | null | undefined) =>
  reason !== 'NO_TRANSCRIPT';

/**
 * 실패 뒤 다시 물을 간격. 더 기다릴 까닭이 없거나 충분히 기다렸으면 false.
 * `checks` 는 지금까지 받은 응답 수다 (TanStack Query 의 dataUpdateCount).
 */
export function latePollInterval(
  reason: SummaryFailureReason | null | undefined,
  checks: number,
): number | false {
  return mayStillArrive(reason) && checks < LATE_POLL_LIMIT ? LATE_POLL_MS : false;
}

/** 실패 안내 문구. `waiting` 은 아직 다시 묻는 중인가 */
export function failureMessage(
  reason: SummaryFailureReason | null | undefined,
  waiting: boolean,
): { title: string; detail: string } {
  if (reason === 'NO_TRANSCRIPT')
    return {
      title: '요약할 대화가 기록되지 않았습니다',
      detail:
        '면접 중 음성이 기록되지 않아 AI 요약을 만들지 않았습니다. 마이크가 켜져 있었는지 확인해주세요.',
    };
  if (waiting)
    return {
      title: 'AI 정리가 늦어지고 있습니다',
      detail:
        '결과가 도착하면 이 화면에 바로 나타납니다. 그동안 녹화와 문답은 먼저 확인할 수 있습니다.',
    };
  return {
    title: '요약을 만들지 못했습니다',
    detail: 'AI 정리에 실패했습니다. 녹화와 문답으로 검토할 수 있습니다.',
  };
}
