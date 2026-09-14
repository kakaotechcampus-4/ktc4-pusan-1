/**
 * 면접관 자기 화면 — 영상 프리뷰와 마이크 입력 레벨.
 *
 * 표현부다. 권한 요청도 트랙 획득도 하지 않고 받은 트랙만 그린다.
 * 여기서 usePermissionCheck 를 부르면 훅 인스턴스가 둘이 되어 권한 프롬프트가
 * 두 번 뜬다 — 트랙은 연결부(pages/InterviewRoom)가 한 번만 얻어 내려준다.
 *
 * 레벨 미터는 볼륨만 표시한다. 녹음이 아니다 —
 * 면접 녹화는 서버 LiveKit Egress 가 담당한다.
 */

import { useEffect, useRef } from 'react';

export interface LocalPreviewProps {
  /** 자기 영상. null 이면 자리만 잡고 안내를 덮는다 */
  videoTrack: MediaStreamTrack | null;
  /** 레벨 미터 소스. null 이면 미터를 숨긴다 */
  audioTrack: MediaStreamTrack | null;
  /**
   * 크기와 테두리 등 겉모습. PiP 와 전체 프리뷰에 같은 컴포넌트를 쓴다.
   *
   * position 유틸리티(absolute·fixed)는 넣지 않는다 — 루트가 내부 오버레이를
   * 위해 relative 를 쓰므로 둘이 충돌한다. 배치는 감싸는 요소가 맡는다.
   */
  className?: string;
}

export function LocalPreview({ videoTrack, audioTrack, className }: LocalPreviewProps) {
  const videoElRef = useRef<HTMLVideoElement>(null);
  const barElRef = useRef<HTMLSpanElement>(null);

  /* 영상 — 기기 점검에서는 LiveKit 래퍼 없이 native MediaStreamTrack 을 바로 붙인다. */
  useEffect(() => {
    const el = videoElRef.current;
    if (!videoTrack || !el) return;

    el.srcObject = new MediaStream([videoTrack]);
    return () => {
      el.srcObject = null;
    };
  }, [videoTrack]);

  /* 마이크 레벨 — 값을 상태나 스토어에 넣지 않는다.
     프레임마다 리렌더가 나면 전사·추천 질문 패널까지 함께 다시 그려진다.
     ref 로 잡은 DOM 의 transform 만 갱신한다. */
  useEffect(() => {
    const bar = barElRef.current;
    if (!audioTrack || !bar) return;

    const AudioContextConstructor =
      window.AudioContext ||
      (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextConstructor) return;

    const ctx = new AudioContextConstructor();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.8;
    analyser.minDecibels = -80;
    analyser.maxDecibels = -20;
    const source = ctx.createMediaStreamSource(new MediaStream([audioTrack]));
    source.connect(analyser);

    // 사용자 제스처 없이 만든 컨텍스트는 suspended 로 시작할 수 있다.
    if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined);

    let raf = 0;
    let stopped = false;
    const levels = new Uint8Array(analyser.frequencyBinCount);
    const loop = () => {
      if (stopped) return;
      analyser.getByteFrequencyData(levels);
      const sum = levels.reduce((acc, level) => acc + level, 0);
      const volume = sum / levels.length / 255;
      bar.style.transform = `scaleX(${Math.min(1, volume * 2.8)})`;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      source.disconnect();
      void ctx.close();
    };
  }, [audioTrack]);

  return (
    <div className={`relative overflow-hidden bg-black/60 ${className ?? ''}`}>
      {/* 트랙 유무로 조건부 렌더하지 않는다 — 이펙트가 도는 시점에 ref 가 비어 있게 된다. */}
      <video
        ref={videoElRef}
        autoPlay
        // 자기 소리를 되받으면 하울링이 난다.
        muted
        playsInline
        // 자기 화면은 거울처럼 좌우를 뒤집는다.
        className="h-full w-full -scale-x-100 object-cover"
      />

      {!videoTrack && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-[13px] text-white/50">카메라 꺼짐</p>
        </div>
      )}

      {audioTrack && (
        <div aria-hidden className="absolute inset-x-1.5 bottom-1.5 h-1 rounded bg-white/20">
          <span
            ref={barElRef}
            className="block h-full origin-left rounded bg-[#5FD6A5]"
            style={{ transform: 'scaleX(0)' }}
          />
        </div>
      )}
    </div>
  );
}
