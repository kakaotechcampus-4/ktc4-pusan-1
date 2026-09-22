import type { Speaker } from '../../types/interview';

/**
 * 화자별 색. 시안(1. full screen video layout)의 상태색을 Tailwind 기본 팔레트로 옮겼다.
 *
 * 색으로 사람을 구분한다 — 면접관은 앰버, 지원자는 에메랄드다.
 * 시안이 "말하는 중"에 쓰는 에메랄드를 지원자에게 준 것은, 면접관이 보는 화면에서
 * 눈이 먼저 가야 하는 쪽이 지원자 발화이기 때문이다.
 */
export const SPEAKER_STYLE: Record<
  Speaker,
  { label: string; text: string; bar: string; border: string }
> = {
  INTERVIEWER: {
    label: '면접관',
    text: 'text-amber-300',
    bar: 'bg-amber-300',
    border: 'border-amber-300',
  },
  CANDIDATE: {
    label: '지원자',
    text: 'text-emerald-300',
    bar: 'bg-emerald-300',
    border: 'border-emerald-300',
  },
};
