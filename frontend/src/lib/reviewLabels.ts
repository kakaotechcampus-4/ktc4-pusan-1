import type { Finding } from '../types/interview';

export const FINDING_LABEL: Record<Finding['type'], string> = {
  COMPETENCY_EVIDENCE: '면접 답변',
  CLAIM_VERIFIED: '지원서 내용 확인',
  CLAIM_CONTRADICTED: '지원서와 다른 설명',
  CLAIM_UNVERIFIED: '추가 확인 필요',
  GAP: '다루지 않음',
};
