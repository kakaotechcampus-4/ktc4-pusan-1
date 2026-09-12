import type { Speaker } from '../../types/interview';

export const SPEAKER_STYLE: Record<Speaker, { label: string; text: string; bar: string }> = {
  INTERVIEWER: { label: '면접관', text: 'text-[#FFC46B]', bar: 'bg-[#FFC46B]' },
  CANDIDATE: { label: '지원자', text: 'text-[#7A97FF]', bar: 'bg-[#7A97FF]' },
};
