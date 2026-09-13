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
}

export function DropZone({ onFiles, disabled }: DropZoneProps) {
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
    <div
      onDragEnter={handleDragEnter}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          if (!disabled) inputRef.current?.click();
        }
      }}
      aria-disabled={disabled}
      className={`rounded-xl border border-dashed p-10 text-center transition-colors ${
        disabled
          ? 'cursor-not-allowed border-white/10 text-white/25'
          : dragging
            ? 'cursor-copy border-[#2B44D6] bg-[#2B44D6]/10 text-[#8FA2FF]'
            : 'cursor-pointer border-white/20 text-white/50 hover:border-white/35'
      }`}
    >
      <p className="text-[15px]">
        {dragging ? '여기에 놓으세요' : 'JD · 회사 문서를 끌어다 놓으세요'}
      </p>
      <p className="mt-1.5 text-[13px] text-white/30">PDF · DOCX · 50MB 이하</p>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          onFiles([...(e.target.files ?? [])]);
          // 같은 파일을 다시 골라도 change 가 나게 비운다.
          e.target.value = '';
        }}
      />
    </div>
  );
}
