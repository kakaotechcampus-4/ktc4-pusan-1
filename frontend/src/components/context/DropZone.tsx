/**
 * 파일을 끌어다 놓거나 눌러서 고르는 영역.
 *
 * 드래그 상태를 depth 로 센다. 자식 요소를 지날 때마다 dragleave 가 튀는데,
 * 그때마다 테두리가 깜빡이면 놓을 곳을 잃은 것처럼 보인다.
 */

import { useRef, useState, type DragEvent } from 'react';
import { ACCEPT_ATTR } from '../../lib/docFile';

export interface DropZoneProps {
  onFiles: (files: File[]) => void;
  /** 업로드 중에는 받지 않는다 */
  disabled?: boolean;
  /** 무엇을 놓는 곳인지 화면마다 다르다 (JD·회사 문서 / 이력서) */
  label?: string;
}

export function DropZone({
  onFiles,
  disabled,
  label = 'JD · 회사 문서를 끌어다 놓으세요',
}: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const depth = useRef(0);

  const handleDragEnter = (e: DragEvent) => {
    e.preventDefault();
    if (disabled) return;
    depth.current += 1;
    if (depth.current === 1) setDragging(true);
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    depth.current -= 1;
    if (depth.current <= 0) {
      depth.current = 0;
      setDragging(false);
    }
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    depth.current = 0;
    setDragging(false);
    if (disabled) return;
    onFiles([...e.dataTransfer.files]);
  };

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onDragEnter={handleDragEnter}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`focus-visible:ring-brand/40 flex w-full flex-col items-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors focus-visible:ring-4 focus-visible:outline-none ${
          disabled
            ? 'border-border-base bg-surface-container text-ink-dim cursor-not-allowed'
            : dragging
              ? 'border-brand bg-brand-tint text-brand-strong cursor-copy'
              : 'border-border-input bg-surface-container text-ink-muted hover:border-brand/50 hover:bg-brand-tint/50 cursor-pointer'
        }`}
      >
        <span
          aria-hidden
          className="material-symbols-outlined bg-surface-panel text-brand shadow-card mb-3 rounded-full p-2.5 text-[24px]"
        >
          upload_file
        </span>
        <span className="text-ink block text-[15px] font-medium">
          {dragging ? '여기에 놓으세요' : label}
        </span>
        <span className="text-ink-dim mt-1 block text-[13px]">PDF · 50MB 이하</span>
      </button>

      <input
        ref={inputRef}
        type="file"
        disabled={disabled}
        multiple
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          onFiles([...(e.target.files ?? [])]);
          // 같은 파일을 다시 골라도 change 가 나게 비운다.
          e.target.value = '';
        }}
      />
    </>
  );
}
