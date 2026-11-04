/** 불러오는 동안 자리를 잡아 두는 회색 막대. 크기는 부르는 쪽이 정한다. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`bg-surface-bright animate-pulse rounded-lg ${className}`} />;
}
