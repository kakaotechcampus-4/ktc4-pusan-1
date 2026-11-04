/**
 * 화면 아래에 잠깐 떴다 사라지는 알림. 어디서든 `toast('복사했습니다')` 로 부른다.
 * 그리는 쪽은 `components/ui/Toast.tsx` 의 `<Toaster />` 하나다 (`main.tsx`).
 */

import { create } from 'zustand';

export type ToastTone = 'info' | 'success' | 'error';

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

/** 읽을 시간. 짧으면 「뭐가 떴다 사라졌다」만 남는다 */
const SHOW_MS = 3500;

let nextId = 0;
export const useToasts = create<{ items: ToastItem[] }>(() => ({ items: [] }));

export function toast(message: string, tone: ToastTone = 'info') {
  const id = ++nextId;
  useToasts.setState((s) => ({ items: [...s.items, { id, message, tone }] }));
  setTimeout(
    () => useToasts.setState((s) => ({ items: s.items.filter((t) => t.id !== id) })),
    SHOW_MS,
  );
}
