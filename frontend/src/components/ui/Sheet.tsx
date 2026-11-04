/**
 * 옆(데스크톱 미리보기) 또는 아래(모바일 메뉴)에서 올라오는 시트.
 *
 * 네이티브 `<dialog>` 의 `showModal()` 을 쓴다 — 포커스 가두기 · Esc 닫기 · 뒤 화면
 * 막기를 브라우저가 해 준다 (`InterviewNavigationDialog` 와 같은 방식).
 */

import { useEffect, useRef, type ReactNode } from 'react';

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  side?: 'right' | 'bottom';
  children: ReactNode;
}

const SIDE = {
  right: 'ml-auto mr-0 h-full max-h-none w-full max-w-md rounded-l-2xl',
  bottom: 'mt-auto mb-0 max-h-[85vh] w-full max-w-none rounded-t-2xl',
};

export function Sheet({ open, onClose, title, side = 'right', children }: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      // Esc 로 닫혀도 부모의 open 이 따라오게 한다.
      onClose={onClose}
      // 시트 바깥(배경)을 누르면 닫는다. 안쪽 클릭은 target 이 dialog 가 아니다.
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className={`bg-surface-panel text-ink shadow-pop backdrop:bg-ink/30 p-0 backdrop:backdrop-blur-[2px] ${SIDE[side]}`}
    >
      <div className="flex h-full flex-col">
        <header className="border-border-base relative flex items-center gap-3 border-b px-5 py-4">
          {side === 'bottom' && (
            <span
              aria-hidden
              className="bg-border-input absolute top-2 left-1/2 h-1 w-10 -translate-x-1/2 rounded-full"
            />
          )}
          <h2 className="text-[16px] font-semibold">{title}</h2>
          <span className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="text-ink-muted hover:bg-surface-bright hover:text-ink rounded-lg p-1.5"
          >
            <span aria-hidden className="material-symbols-outlined text-[20px]">
              close
            </span>
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </dialog>
  );
}
