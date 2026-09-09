/**
 * 카메라·마이크 권한 확인 — 방 접속보다 먼저 수행한다.
 *
 * LiveKit 서버가 필요 없다. createLocalTracks 는 내부적으로 getUserMedia 만 쓰므로
 * BE 의 입장 토큰 없이도 장비 상태를 확인할 수 있다.
 *
 * 여기서 확보한 트랙을 useInterviewRoom 이 그대로 발행한다.
 * 권한 프롬프트를 두 번 띄우지 않기 위해 트랙 획득 지점은 앱 전체에서 이 훅 하나다.
 *
 * 전체화면 안내 UI 는 만들지 않는다 — 상태만 돌려주고 화면은 호출부가 결정한다.
 */

import {
  createLocalTracks,
  LocalAudioTrack,
  LocalVideoTrack,
  MediaDeviceFailure,
  type LocalTrack,
} from 'livekit-client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { AudioCaptureOptions, VideoCaptureOptions } from 'livekit-client';

/**
 * 캡처 설정. useInterviewRoom 의 Room 기본값도 이 상수를 쓴다 —
 * 프리뷰에서 잡은 트랙과 방에 발행하는 트랙의 설정이 어긋나면 안 되기 때문이다.
 */
export const VIDEO_CAPTURE: VideoCaptureOptions = {
  // 면접관은 지원자를 크게 보므로 원본 해상도를 유지한다.
  resolution: { width: 1280, height: 720 },
};

export const AUDIO_CAPTURE: AudioCaptureOptions = {
  echoCancellation: true,
  noiseSuppression: true,
};

export type PermissionStatus =
  /** 프롬프트 대기 */
  | 'requesting'
  /** 트랙 확보 */
  | 'granted'
  /** 사용자가 거부 / 브라우저가 차단 */
  | 'denied'
  /** 장치가 없음 */
  | 'not-found'
  /** 다른 앱이 장치를 점유 */
  | 'in-use'
  /** 그 외 */
  | 'failed';

export interface PermissionCheckResult {
  status: PermissionStatus;
  videoTrack: LocalVideoTrack | null;
  audioTrack: LocalAudioTrack | null;
  /** 원본 DOMException.name — 로그용. 정상이면 null */
  errorName: string | null;
  /**
   * 트랙 소유권을 호출자에게 넘긴다. 호출 이후 이 훅은 트랙을 stop 하지 않는다.
   * publishTrack 이 성공한 직후에만 호출해야 한다 — 그 전에 넘기면 언마운트 시
   * 아무도 stop 하지 않아 카메라가 켜진 채로 남는다.
   */
  release: () => void;
}

/** DOMException 을 화면이 구분할 수 있는 상태로 바꾼다. */
function toStatus(error: unknown): PermissionStatus {
  // 브라우저·버전별 별칭(PermissionDeniedError, TrackStartError 등)까지 라이브러리가 처리한다.
  switch (MediaDeviceFailure.getFailure(error)) {
    case MediaDeviceFailure.PermissionDenied:
      return 'denied';
    case MediaDeviceFailure.NotFound:
      return 'not-found';
    case MediaDeviceFailure.DeviceInUse:
      return 'in-use';
    default:
      return 'failed';
  }
}

const INITIAL = {
  status: 'requesting' as PermissionStatus,
  videoTrack: null as LocalVideoTrack | null,
  audioTrack: null as LocalAudioTrack | null,
  errorName: null as string | null,
};

export function usePermissionCheck(): PermissionCheckResult {
  // 상태를 한 덩어리로 두고 한 번에 set 한다. 나눠 두면 트랙은 있는데
  // status 는 아직 requesting 인 중간 렌더가 생긴다.
  const [state, setState] = useState(INITIAL);

  /** cleanup 이 stop 해야 할 실제 트랙 목록 */
  const tracksRef = useRef<LocalTrack[]>([]);
  /** 소유권이 넘어갔는지. true 면 cleanup 은 stop 하지 않는다 */
  const releasedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const tracks = await createLocalTracks({ audio: AUDIO_CAPTURE, video: VIDEO_CAPTURE });

        // getUserMedia 는 취소할 수 없다. StrictMode 1회차처럼 이미 정리된 뒤에
        // 도착한 트랙은 여기서 즉시 회수한다 — tracksRef 에 넣으면 2회차 트랙을 덮어쓴다.
        if (cancelled) {
          tracks.forEach((t) => t.stop());
          return;
        }

        tracksRef.current = tracks;
        setState({
          status: 'granted',
          // 반환 타입이 LocalTrack[] 이라 kind 비교로는 타입이 좁혀지지 않는다.
          videoTrack: tracks.find((t) => t instanceof LocalVideoTrack) ?? null,
          audioTrack: tracks.find((t) => t instanceof LocalAudioTrack) ?? null,
          errorName: null,
        });
      } catch (e) {
        if (cancelled) return;
        setState({
          status: toStatus(e),
          videoTrack: null,
          audioTrack: null,
          errorName: e instanceof Error ? e.name : null,
        });
      }
    })();

    return () => {
      cancelled = true;
      if (!releasedRef.current) tracksRef.current.forEach((t) => t.stop());
      tracksRef.current = [];
    };
  }, []);

  const release = useCallback(() => {
    releasedRef.current = true;
  }, []);

  return { ...state, release };
}
