/**
 * 기기 점검 — 카메라·마이크 확인 (S0.5)
 *
 * 순서는 `join → 점검 → 방 접속` 이다 (issue #9).
 * 잘못된 링크가 권한 프롬프트보다 먼저 걸려야 하므로 join 다음에 온다.
 *
 * 여기서 얻은 트랙을 그대로 방에 발행한다 — 권한 프롬프트를 두 번 띄우지 않기 위해
 * 트랙 획득 지점은 앱 전체에서 usePermissionCheck 하나다.
 */

import { LocalPreview } from '../components/interview/LocalPreview';
import { usePermissionCheck, type PermissionStatus } from '../hooks/usePermissionCheck';
import type { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';

/** 상태별 안내. 사용자가 다음에 뭘 해야 하는지까지 적는다. */
const GUIDE: Record<Exclude<PermissionStatus, 'granted'>, { title: string; detail: string }> = {
  requesting: {
    title: '카메라와 마이크를 확인하는 중입니다',
    detail: '브라우저가 권한을 물어보면 허용을 눌러주세요.',
  },
  denied: {
    title: '카메라·마이크 권한이 거부되었습니다',
    detail:
      '주소창 왼쪽의 자물쇠 아이콘을 눌러 카메라와 마이크를 허용으로 바꾼 뒤, 이 페이지를 새로고침해주세요.',
  },
  'not-found': {
    title: '카메라 또는 마이크를 찾을 수 없습니다',
    detail: '기기가 연결되어 있는지 확인한 뒤 새로고침해주세요.',
  },
  'in-use': {
    title: '다른 프로그램이 카메라를 사용 중입니다',
    detail: '화상회의 앱이나 다른 탭을 닫은 뒤 새로고침해주세요.',
  },
  failed: {
    title: '기기를 준비하지 못했습니다',
    detail: '새로고침 후에도 같은 문제가 생기면 다른 브라우저로 시도해주세요.',
  },
};

export interface DeviceCheckPageProps {
  /** 점검 완료 — 확보한 트랙을 그대로 방으로 넘긴다 */
  onReady: (tracks: {
    videoTrack: LocalVideoTrack | null;
    audioTrack: LocalAudioTrack | null;
    release: () => void;
  }) => void;
}

export default function DeviceCheckPage({ onReady }: DeviceCheckPageProps) {
  const { status, videoTrack, audioTrack, errorName, release } = usePermissionCheck();
  const guide = status === 'granted' ? null : GUIDE[status];

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold text-white">기기 점검</h1>
        <p className="mt-2 text-[15px] text-white/60">
          입장 전에 카메라와 마이크가 정상인지 확인합니다.
        </p>

        <LocalPreview
          videoTrack={videoTrack}
          audioTrack={audioTrack}
          className="mt-6 aspect-video w-full rounded-xl"
        />

        {guide && (
          <div aria-live="polite" className="mt-5">
            <p className="text-[15px] font-medium text-[#FFC46B]">{guide.title}</p>
            <p className="mt-1.5 text-sm leading-relaxed text-white/55">{guide.detail}</p>
            {errorName && <p className="mt-2 font-mono text-[12px] text-white/25">{errorName}</p>}
          </div>
        )}

        {status === 'granted' && (
          <p className="mt-5 text-[15px] text-[#5FD6A5]">
            카메라와 마이크가 준비되었습니다. 말해보면 아래 막대가 움직입니다.
          </p>
        )}

        <button
          type="button"
          onClick={() => onReady({ videoTrack, audioTrack, release })}
          disabled={status !== 'granted'}
          className="mt-6 w-full rounded-lg bg-[#2B44D6] py-3.5 text-[15px] font-medium text-white transition hover:bg-[#243AB8] disabled:bg-white/10 disabled:text-white/35"
        >
          면접 시작하기
        </button>
      </div>
    </div>
  );
}
