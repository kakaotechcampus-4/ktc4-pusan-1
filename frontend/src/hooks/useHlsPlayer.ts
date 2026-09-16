/**
 * HLS 녹화를 <video> 에 붙이고, 원하는 시점으로 이동시킨다.
 *
 * hls.js 를 먼저 쓰고, MSE 가 없는 환경(iOS Safari 등)만 네이티브 재생으로 넘긴다.
 *
 * 순서를 반대로 두면 안 된다. 최근 Chrome 은 canPlayType('application/vnd.apple.mpegurl') 에
 * 빈 문자열이 아닌 값을 돌려주는데, 그 경로로 넣으면 영상이 로딩 상태에서 멈추는 것을 확인했다.
 */

import Hls from 'hls.js';
import { useCallback, useEffect, useRef, useState } from 'react';

const hlsJsSupported = Hls.isSupported();

const nativeHls =
  !hlsJsSupported &&
  typeof document !== 'undefined' &&
  document.createElement('video').canPlayType('application/vnd.apple.mpegurl') !== '';

/** 이 브라우저에서 HLS 를 재생할 방법이 있는가 */
const playable = hlsJsSupported || nativeHls;

function jump(video: HTMLVideoElement, sec: number) {
  video.currentTime = sec;
  // 사용자가 누른 직후라 대부분 재생되지만, 브라우저가 막으면 멈춘 채 둔다.
  video.play().catch(() => {});
}

export function useHlsPlayer(src: string | undefined) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // 실패를 src 에 묶어 둔다. 다른 녹화로 바뀌면 따로 초기화하지 않아도 실패 표시가 풀린다.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src || !playable) return;

    if (nativeHls) {
      video.src = src;
      const onError = () => setFailedSrc(src);
      video.addEventListener('error', onError);
      return () => {
        video.removeEventListener('error', onError);
        video.removeAttribute('src');
        video.load();
      };
    }

    const hls = new Hls();
    hls.on(Hls.Events.ERROR, (_event, data) => {
      // 치명적이지 않은 오류(세그먼트 재시도 등)는 hls.js 가 스스로 복구한다.
      if (data.fatal) setFailedSrc(src);
    });
    hls.loadSource(src);
    hls.attachMedia(video);
    return () => hls.destroy();
  }, [src]);

  /** 메타데이터를 받기 전에 요청된 이동. 가장 마지막 요청 하나만 남긴다. */
  const pendingSeek = useRef<number | null>(null);

  // 메타데이터를 받기 전에 currentTime 을 넣으면 무시된다. 그 사이의 클릭은 모아 두었다가
  // 준비되면 적용한다. 리스너를 클릭마다 붙이면 여러 번 누를 때 쌓이고, 녹화가 바뀐 뒤에도
  // 이전 요청이 새 영상에 적용된다.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src) return;
    const flush = () => {
      if (pendingSeek.current === null) return;
      jump(video, pendingSeek.current);
      pendingSeek.current = null;
    };
    video.addEventListener('loadedmetadata', flush);
    return () => {
      video.removeEventListener('loadedmetadata', flush);
      pendingSeek.current = null;
    };
  }, [src]);

  const seekTo = useCallback((sec: number) => {
    const video = videoRef.current;
    if (!video) return;
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) jump(video, sec);
    else pendingSeek.current = sec;
  }, []);

  const failed = Boolean(src) && (!playable || failedSrc === src);

  return { videoRef, seekTo, failed };
}
