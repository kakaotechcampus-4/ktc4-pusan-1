import type { ReactNode } from 'react';

export interface EmptyStateProps {
  /** 일러스트 주소. 장식이라 대체 텍스트를 비운다 */
  image?: string;
  title: string;
  description?: ReactNode;
  /** 다음에 할 일 — 빈 화면에서 멈추지 않게 버튼 하나를 둔다 */
  action?: ReactNode;
}

export function EmptyState({ image, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {image && <img src={image} alt="" className="mb-5 h-28 w-auto select-none" />}
      <p className="text-ink text-[17px] font-semibold">{title}</p>
      {description && (
        <p className="text-ink-muted mt-1.5 max-w-sm text-[14px] leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
