/**
 * IRYA 로고 — 말풍선 안의 음성 막대. 가운데 민트 막대가 「AI 가 듣고 정리한다」를 뜻한다.
 *
 * 모양은 `public/favicon.svg` 와 같다. 고칠 때 둘을 함께 고친다.
 */

export function LogoMark({ className = 'h-8 w-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden className={className}>
      <rect x="2" y="3" width="36" height="27" rx="9" className="fill-brand" />
      <path
        d="M8 27 6.5 37 17 29.5Z"
        strokeWidth="1.5"
        strokeLinejoin="round"
        className="fill-brand stroke-brand"
      />
      <rect x="11.5" y="12" width="5" height="10" rx="2.5" fill="#fff" />
      <rect x="17.5" y="8.5" width="5" height="17" rx="2.5" className="fill-accent" />
      <rect x="23.5" y="12" width="5" height="10" rx="2.5" fill="#fff" />
    </svg>
  );
}

/** 마크 + 글자. 링크 안에 넣으면 그 자체가 「IRYA」 라는 이름이 된다 */
export function Logo({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const mark = { sm: 'h-6 w-6', md: 'h-8 w-8', lg: 'h-10 w-10' }[size];
  const text = { sm: 'text-[15px]', md: 'text-[18px]', lg: 'text-[22px]' }[size];
  return (
    <span className="text-ink inline-flex items-center gap-2">
      <LogoMark className={mark} />
      <span className={`font-bold tracking-tight ${text}`}>IRYA</span>
    </span>
  );
}
