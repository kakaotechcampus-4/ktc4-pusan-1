/**
 * 기기 점검 — 카메라·마이크 확인 (S0.5)
 *
 * 순서는 `join → 점검 → 방 접속` 이다 (issue #9).
 * 잘못된 링크가 권한 프롬프트보다 먼저 걸려야 하므로 join 다음에 온다.
 *
 * 여기서 얻은 트랙을 그대로 방에 발행한다 — 권한 프롬프트를 두 번 띄우지 않기 위해
 * 트랙 획득 지점은 앱 전체에서 usePermissionCheck 하나다.
 */

import { useCallback, useEffect, useState } from 'react';
import { usePermissionCheck, type PermissionStatus } from '../hooks/usePermissionCheck';
import { prepareLiveKitConnection, preloadLiveKit } from '../lib/livekit';
import { DeviceCheckSurface } from './DeviceCheckSurface';

/** 상태별 안내. 사용자가 다음에 뭘 해야 하는지까지 적는다. */
const GUIDE: Record<Exclude<PermissionStatus, 'granted'>, { title: string; detail: string }> = {
  requesting: {
    title: '카메라와 마이크를 확인하는 중입니다',
    detail: '브라우저가 권한을 물어보면 허용을 눌러주세요.',
  },
  denied: {
    title: '카메라·마이크 권한이 거부되었습니다',
    detail: '주소창 왼쪽의 자물쇠 아이콘에서 카메라와 마이크를 허용한 뒤 기기 재점검을 눌러주세요.',
  },
  'not-found': {
    title: '카메라 또는 마이크를 찾을 수 없습니다',
    detail: '기기를 연결한 뒤 기기 재점검을 눌러주세요.',
  },
  'in-use': {
    title: '다른 프로그램이 카메라를 사용 중입니다',
    detail: '화상회의 앱이나 다른 탭을 닫은 뒤 기기 재점검을 눌러주세요.',
  },
  failed: {
    title: '기기를 준비하지 못했습니다',
    detail: '기기 재점검 후에도 같은 문제가 생기면 다른 브라우저로 시도해주세요.',
  },
};

export interface DeviceCheckPageProps {
  livekitConnection?: {
    livekitUrl: string;
    token: string;
  };
  /** 점검 완료 — 확보한 트랙을 그대로 방으로 넘긴다 */
  onReady: (tracks: {
    videoTrack: MediaStreamTrack | null;
    audioTrack: MediaStreamTrack | null;
    release: () => void;
  }) => void;
}

export default function DeviceCheckPage({ livekitConnection, onReady }: DeviceCheckPageProps) {
  const { status, videoTrack, audioTrack, errorName, release, retry } = usePermissionCheck();
  const [starting, setStarting] = useState(false);
  const [soundNotice, setSoundNotice] = useState('');
  const guide = status === 'granted' ? null : GUIDE[status];

  const warmLiveKit = useCallback(() => {
    if (!livekitConnection) {
      preloadLiveKit();
      return;
    }
    void prepareLiveKitConnection(livekitConnection.livekitUrl, livekitConnection.token).catch(
      () => undefined,
    );
  }, [livekitConnection]);

  useEffect(() => {
    if (status === 'granted') warmLiveKit();
  }, [status, warmLiveKit]);

  const handleStart = () => {
    setStarting(true);
    onReady({ videoTrack, audioTrack, release });
  };

  const playSoundTest = async () => {
    try {
      const context = new AudioContext();
      await context.resume();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = 660;
      gain.gain.value = 0.06;
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.onended = () => void context.close();
      oscillator.start();
      oscillator.stop(context.currentTime + 0.3);
      setSoundNotice('소리가 들리면 출력 장치가 연결된 상태입니다.');
    } catch {
      setSoundNotice('소리를 재생하지 못했습니다. 브라우저의 출력 장치를 확인해주세요.');
    }
  };

  return (
    <DeviceCheckSurface
      status={status}
      videoTrack={videoTrack}
      audioTrack={audioTrack}
      errorName={errorName}
      guide={guide}
      starting={starting}
      soundNotice={soundNotice}
      onSoundTest={() => void playSoundTest()}
      onRetry={() => {
        setSoundNotice('');
        retry();
      }}
      onStart={handleStart}
      onPreload={warmLiveKit}
    />
  );
}
