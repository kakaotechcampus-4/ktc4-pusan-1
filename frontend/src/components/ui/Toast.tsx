/** 화면 아래 알림을 그린다. 앱에 하나만 둔다 (`main.tsx`). 부르는 쪽은 `lib/toast.ts`. */

import { useToasts, type ToastTone } from '../../lib/toast';

const ICON: Record<ToastTone, string> = { info: 'info', success: 'check_circle', error: 'error' };
const ICON_COLOR: Record<ToastTone, string> = {
  info: 'text-brand-soft',
  success: 'text-accent',
  error: 'text-danger',
};

export function Toaster() {
  const items = useToasts((s) => s.items);
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 sm:bottom-6"
    >
      {items.map((t) => (
        <div
          key={t.id}
          role={t.tone === 'error' ? 'alert' : 'status'}
          className="bg-ink shadow-pop pointer-events-auto flex max-w-md items-center gap-2.5 rounded-xl px-4 py-3 text-[14px] text-white"
        >
          <span
            aria-hidden
            className={`material-symbols-outlined text-[20px] ${ICON_COLOR[t.tone]}`}
          >
            {ICON[t.tone]}
          </span>
          {t.message}
        </div>
      ))}
    </div>
  );
}
