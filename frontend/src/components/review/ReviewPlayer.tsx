/**
 * 녹화 재생 영역. 선택한 질문의 문답을 영상 우하단에 겹쳐 보여준다.
 */

import type { RefObject } from 'react';
import { fmt } from '../../lib/format';
import type { Moment } from '../../types/interview';

export interface ReviewPlayerProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  active: Moment | undefined;
  /** 녹화를 재생할 수 없을 때 */
  failed: boolean;
}

export function ReviewPlayer({ videoRef, active, failed }: ReviewPlayerProps) {
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black">
      <video
        ref={videoRef}
        controls
        playsInline
        className="absolute inset-0 h-full w-full object-contain"
      />

      {failed && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80">
          <p className="text-[15px] text-[#FFC46B]">녹화를 재생하지 못했습니다.</p>
        </div>
      )}

      {active && !failed && (
        <>
          <span className="pointer-events-none absolute top-4 left-4 rounded-md bg-black/50 px-2.5 py-1 font-mono text-[13px] text-white backdrop-blur-sm">
            {fmt(active.atSec)}
          </span>

          {/* 영상을 가리지 않도록 폭을 제한하고, 컨트롤 막대 위로 띄운다. 좁은 화면에서는 감춘다. */}
          <div
            key={active.id}
            className="absolute right-4 bottom-16 hidden max-h-[calc(100%-96px)] w-[36%] animate-[slidein_.2s_ease-out] flex-col gap-4 overflow-auto rounded-xl bg-black/60 px-5 py-4 backdrop-blur-xl md:flex"
          >
            <div>
              <span className="text-[11px] font-semibold tracking-[.08em] text-white/55">질문</span>
              <p className="mt-1.5 text-[16px] leading-[1.5] font-semibold text-white">
                {active.question}
              </p>
            </div>
            <div>
              <span className="text-[11px] font-semibold tracking-[.08em] text-white/55">답변</span>
              <p className="mt-1.5 text-[14px] leading-[1.65] text-white/90">{active.answer}</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
