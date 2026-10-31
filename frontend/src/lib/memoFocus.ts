import type { MouseEvent } from 'react';

/** 마우스 조작으로 메모의 캐럿을 잃지 않게 하며 키보드 이동은 막지 않는다. */
export function preserveMemoFocus(event: MouseEvent) {
  if (event.button === 0 && document.activeElement?.getAttribute('data-live-memo') === 'true')
    event.preventDefault();
}
