import type { Speaker } from '../../types/interview';

/**
 * 화자별 색. 라이트 테마 토큰을 쓴다 (#232). 글자색은 흰 바탕에서 4.5:1 을 넘는다.
 *
 * 색으로 사람을 구분한다 — 면접관은 앰버(warning), 지원자는 민트(accent)다.
 * 시안이 "말하는 중"에 쓰는 에메랄드를 지원자에게 준 것은, 면접관이 보는 화면에서
 * 눈이 먼저 가야 하는 쪽이 지원자 발화이기 때문이다.
 */
export const SPEAKER_STYLE: Record<
  Speaker,
  { label: string; text: string; bar: string; border: string }
> = {
  INTERVIEWER: {
    label: '면접관',
    text: 'text-warning',
    bar: 'bg-warning',
    border: 'border-warning',
  },
  CANDIDATE: {
    label: '지원자',
    text: 'text-accent-strong',
    bar: 'bg-accent',
    border: 'border-accent',
  },
};
