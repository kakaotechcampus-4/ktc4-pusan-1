import type { Consent, SessionState } from '../types/interview';

type ConsentSource = Pick<SessionState, 'consent' | 'consentedAt'> & {
  agreedAt?: string;
  version?: string;
  policyVersion?: string;
};

export function consentRequest(
  state: Pick<SessionState, 'consent' | 'consentedAt'>,
  version: string,
) {
  if ('consentedAt' in state) return { policyVersion: version };
  if ('consent' in state) return { version };
  throw new Error('서버의 동의 기능을 확인하지 못했습니다.');
}

export function readConsent(source: ConsentSource): Consent | null {
  const agreedAt = source.consent?.agreedAt ?? source.consentedAt ?? source.agreedAt;
  if (typeof agreedAt !== 'string' || !Number.isFinite(Date.parse(agreedAt))) return null;
  const version = source.consent?.version ?? source.policyVersion ?? source.version;
  return { agreedAt, version: typeof version === 'string' ? version : null };
}
