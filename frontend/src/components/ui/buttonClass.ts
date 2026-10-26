/**
 * 버튼 모양. 링크(`<Link>`)도 같은 모양을 써야 해서 컴포넌트와 따로 둔다 —
 * 컴포넌트 파일에 함수를 같이 내보내면 Fast Refresh 가 깨진다.
 */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'accent' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-brand text-white hover:bg-brand-strong',
  secondary: 'border border-border-base bg-surface-panel text-ink hover:bg-surface-bright',
  ghost: 'text-ink-muted hover:bg-surface-bright hover:text-ink',
  accent: 'bg-accent text-white hover:bg-accent-strong',
  danger: 'bg-danger text-white hover:brightness-95',
};

const SIZE: Record<ButtonSize, string> = {
  sm: 'h-9 gap-1.5 rounded-lg px-3 text-[13px]',
  md: 'h-11 gap-2 rounded-xl px-4 text-[15px]',
  lg: 'h-13 gap-2 rounded-xl px-6 text-base',
};

export function buttonClass(variant: ButtonVariant = 'primary', size: ButtonSize = 'md') {
  return `inline-flex shrink-0 items-center justify-center font-semibold whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-brand/40 focus-visible:ring-offset-2 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]}`;
}
