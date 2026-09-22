/**
 * 녹화 재생 영역. 선택한 질문의 문답을 영상 우하단에 겹쳐 보여준다.
 *
 * 영상 아래 상태 줄에 현재 재생 위치와 고른 질문을 크게 적는다 — 시안의 구성이되,
 * 브라우저 기본 컨트롤을 가리지 않도록 영상 밖으로 내렸다.
 */

import { useEffect, useState, type RefObject } from 'react';
import { fmt } from '../../lib/format';
import type { Moment } from '../../types/interview';

/** 건너뛰기 버튼이 옮기는 간격(초) */
const SKIP_SEC = 10;

export interface ReviewPlayerProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  active: Moment | undefined;
  /** 고른 질문이 몇 번째인지(1부터). active 가 있을 때만 의미가 있다. */
  activeNo: number;
  candidateName: string;
  durationSec: number;
  /** 녹화를 재생할 수 없을 때 */
  failed: boolean;
}

export function ReviewPlayer({
  videoRef,
  active,
  activeNo,
  candidateName,
  durationSec,
  failed,
}: ReviewPlayerProps) {
  // 상태 줄에 적을 현재 위치. 초 단위로 끊어 두면 같은 값으로는 다시 그리지 않는다.
  const [atSec, setAtSec] = useState(0);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const sync = () => setAtSec(Math.floor(video.currentTime));
    video.addEventListener('timeupdate', sync);
    video.addEventListener('seeked', sync);
    return () => {
      video.removeEventListener('timeupdate', sync);
      video.removeEventListener('seeked', sync);
    };
  }, [videoRef]);

  const skip = (delta: number) => {
    const video = videoRef.current;
    if (!video) return;
    // 메타데이터 전에는 duration 이 NaN 이라 알고 있는 길이로 막는다.
    const end = video.duration || durationSec;
    video.currentTime = Math.max(0, Math.min(end, video.currentTime + delta));
  };

  return (
    <section className="border-border-base bg-surface-panel overflow-hidden rounded-2xl border">
      <div className="relative aspect-video w-full bg-black">
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

        {!failed && (
          <span className="pointer-events-none absolute top-4 left-4 flex items-center gap-2 rounded-full bg-black/50 px-3 py-1 text-[12px] text-white/90 backdrop-blur-sm">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full border border-white/70" />
            원본 녹화 · {candidateName}
          </span>
        )}

        {active && !failed && (
          /* 영상을 가리지 않도록 폭을 제한하고, 컨트롤 막대 위로 띄운다. 좁은 화면에서는 감춘다. */
          <div
            key={active.id}
            className="bg-surface-panel/92 ring-border-base absolute right-4 bottom-16 hidden max-h-[calc(100%-96px)] w-[36%] animate-[slidein_.2s_ease-out] flex-col gap-3 overflow-auto rounded-xl px-5 py-4 shadow-[0_16px_40px_rgba(0,0,0,0.45)] ring-1 backdrop-blur-xl md:flex"
          >
            <div className="flex items-center gap-2">
              <span className="bg-brand rounded-full px-2 py-0.5 font-mono text-[11px] font-semibold text-white">
                Q{activeNo}
              </span>
              <span className="text-ink-dim font-mono text-[12px]">{fmt(active.atSec)}</span>
            </div>
            <p className="text-ink text-[16px] leading-[1.5] font-semibold">{active.question}</p>
            <p className="border-border-base text-ink/85 border-t pt-3 text-[14px] leading-[1.65]">
              {active.answer}
            </p>
          </div>
        )}
      </div>

      <div className="border-border-base bg-surface-container flex flex-wrap items-center gap-x-5 gap-y-3 border-t px-5 py-4">
        <p className="flex items-baseline gap-1.5 font-mono tracking-tight">
          <span className="text-ink text-3xl font-bold">{fmt(atSec)}</span>
          <span className="text-ink-dim text-[15px]">/ {fmt(durationSec)}</span>
        </p>

        <div className="min-w-0 flex-1">
          {active ? (
            <>
              <p className="text-brand-soft truncate text-[14px] font-medium">
                Q{activeNo} · {active.question}
              </p>
              <p className="text-ink-dim truncate text-[12px]">
                이 질문이 시작된 시점부터 재생합니다.
              </p>
            </>
          ) : (
            <p className="text-ink-dim text-[13px]">
              타임라인이나 아래 목록에서 질문을 고르면 그 시점부터 재생합니다.
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <SkipButton onClick={() => skip(-SKIP_SEC)} disabled={failed} label="10초 뒤로">
            replay_10
          </SkipButton>
          <SkipButton onClick={() => skip(SKIP_SEC)} disabled={failed} label="10초 앞으로">
            forward_10
          </SkipButton>
        </div>
      </div>
    </section>
  );
}

function SkipButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  /** Material Symbols 아이콘 이름 */
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      // 아이콘 폰트가 늦게 뜨는 동안 글자("replay_10")가 비어져 나오지 않게 잘라 둔다.
      className="border-border-base bg-surface-bright text-ink-muted hover:text-ink flex h-9 w-9 items-center justify-center overflow-hidden rounded-full border transition disabled:opacity-40"
    >
      <span aria-hidden className="material-symbols-outlined text-[20px]">
        {children}
      </span>
    </button>
  );
}
