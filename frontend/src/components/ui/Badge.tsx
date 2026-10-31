import type { ReactNode } from 'react';

export type BadgeTone = 'neutral' | 'brand' | 'accent' | 'warning' | 'danger';

const TONE: Record<BadgeTone, string> = {
  neutral: 'bg-surface-bright text-ink-muted',
  brand: 'bg-brand-tint text-brand-strong',
  accent: 'bg-accent-tint text-accent-strong',
  warning: 'bg-warning-tint text-warning',
  danger: 'bg-danger-tint text-danger',
};

/** 상태 · 종류를 짧게 적는 알약. 색만으로 뜻을 전하지 않게 글자를 꼭 넣는다. */
export function Badge({ tone = 'neutral', children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}
