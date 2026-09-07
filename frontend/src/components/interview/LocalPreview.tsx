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

import { createAudioAnalyser, type LocalAudioTrack, type LocalVideoTrack } from 'livekit-client';
import { useEffect, useRef } from 'react';

export interface LocalPreviewProps {
  /** 자기 영상. null 이면 자리만 잡고 안내를 덮는다 */
  videoTrack: LocalVideoTrack | null;
  /** 레벨 미터 소스. null 이면 미터를 숨긴다 */
  audioTrack: LocalAudioTrack | null;
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

  /* 영상 — srcObject 를 직접 넣지 않고 attach 를 쓴다.
     attach 는 요소를 트랙에 등록해두므로 장치 변경이나 mute 로 내부
     MediaStreamTrack 이 교체될 때 자동으로 다시 붙는다. */
  useEffect(() => {
    const el = videoElRef.current;
    if (!videoTrack || !el) return;

    videoTrack.attach(el);
    // 인자를 주지 않으면 다른 곳의 부착까지 전부 떼어낸다.
    return () => void videoTrack.detach(el);
  }, [videoTrack]);

  /* 마이크 레벨 — 값을 상태나 스토어에 넣지 않는다.
     프레임마다 리렌더가 나면 전사·추천 질문 패널까지 함께 다시 그려진다.
     ref 로 잡은 DOM 의 transform 만 갱신한다. */
  useEffect(() => {
    const bar = barElRef.current;
    if (!audioTrack || !bar) return;

    const { calculateVolume, analyser, cleanup } = createAudioAnalyser(audioTrack, {
      // 클론하면 우리가 stop 책임을 하나 더 지게 된다. 원본을 그대로 읽는다.
      cloneTrack: false,
      fftSize: 1024,
      smoothingTimeConstant: 0.8,
      // 기본 창(-100 ~ -80dB)은 좁아서 말하면 늘 최대치로 포화된다. 미터용으로 넓힌다.
      minDecibels: -80,
      maxDecibels: -20,
    });

    // 사용자 제스처 없이 만든 컨텍스트는 suspended 로 시작할 수 있다.
    const ctx = analyser.context;
    if (ctx.state === 'suspended' && ctx instanceof AudioContext) void ctx.resume();

    let raf = 0;
    let stopped = false;
    const loop = () => {
      if (stopped) return;
      bar.style.transform = `scaleX(${Math.min(1, calculateVolume() * 1.6)})`;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      void cleanup();
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
