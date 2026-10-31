import type { HTMLAttributes } from 'react';

/** 흰 바탕 카드. 화면의 묶음 하나가 카드 하나다. */
export function Card({ className = '', ...rest }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={`border-border-base bg-surface-panel shadow-card rounded-2xl border p-5 sm:p-6 ${className}`}
      {...rest}
    />
  );
}
