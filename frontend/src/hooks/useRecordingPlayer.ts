/**
 * 녹화를 <video> 에 붙이고, 전사 시각으로 이동시킨다.
 *
 * BE 가 합쳐 주는 파일은 WebM(VP8 + Opus) 하나다. HLS 가 아니라 `src` 에 바로 넣는다 —
 * hls.js 로 감쌀 이유가 없고, 감싸면 MSE 가 없는 환경에서 오히려 재생이 막힌다.
 *
 * Safari 26.5 에서 VP8 + Opus WebM 이 재생·탐색까지 되는 것을 실제로 확인했다
 * (VP9 는 메타데이터만 읽고 멈추므로 publish 코덱이 바뀌면 여기가 깨진다).
 *
 * `canPlayType` 으로 미리 거르지 않는다. 같은 확인에서 Safari 가 재생하지 못하는
 * VP9 에도 `"probably"` 를 돌려줬다 — 믿을 값이 아니다. 대신 실제 `error` 이벤트만 본다.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { toVideoSec } from '../lib/recordingTime';

function jump(video: HTMLVideoElement, sec: number) {
  video.currentTime = sec;
  // 사용자가 누른 직후라 대부분 재생되지만, 브라우저가 막으면 멈춘 채 둔다.
  video.play().catch(() => {});
}

export function useRecordingPlayer(src: string | undefined, offsetMs: number) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // 실패를 src 에 묶어 둔다. 서명 URL 이 갱신되면 따로 초기화하지 않아도 실패 표시가 풀린다.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src) return;

    video.src = src;
    const onError = () => setFailedSrc(src);
    video.addEventListener('error', onError);
    return () => {
      video.removeEventListener('error', onError);
      video.removeAttribute('src');
      video.load();
    };
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
      jump(video, toVideoSec(pendingSeek.current, offsetMs));
      pendingSeek.current = null;
    };
    video.addEventListener('loadedmetadata', flush);
    return () => {
      video.removeEventListener('loadedmetadata', flush);
      pendingSeek.current = null;
    };
  }, [src, offsetMs]);

  /** 전사 기준 초를 받는다. 녹화 파일 기준으로 바꾸는 건 이 안에서 한다 */
  const seekTo = useCallback(
    (atSec: number) => {
      const video = videoRef.current;
      if (!video) return;
      const sec = toVideoSec(atSec, offsetMs);
      if (video.readyState >= HTMLMediaElement.HAVE_METADATA) jump(video, sec);
      else pendingSeek.current = atSec;
    },
    [offsetMs],
  );

  const failed = Boolean(src) && failedSrc === src;

  return { videoRef, seekTo, failed };
}
