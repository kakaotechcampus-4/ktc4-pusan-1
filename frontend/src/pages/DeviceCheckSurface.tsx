import { LocalPreview } from '../components/interview/LocalPreview';
import type { PermissionStatus } from '../hooks/usePermissionCheck';

interface DeviceCheckSurfaceProps {
  status: PermissionStatus;
  videoTrack: MediaStreamTrack | null;
  audioTrack: MediaStreamTrack | null;
  errorName: string | null;
  guide: { title: string; detail: string } | null;
  starting: boolean;
  soundNotice: string;
  onSoundTest: () => void;
  onRetry: () => void;
  onStart: () => void;
  onPreload: () => void;
}

export function DeviceCheckSurface({
  status,
  videoTrack,
  audioTrack,
  errorName,
  guide,
  starting,
  soundNotice,
  onSoundTest,
  onRetry,
  onStart,
  onPreload,
}: DeviceCheckSurfaceProps) {
  const ready = status === 'granted';

  return (
    <div className="min-h-full bg-[#121316] px-4 py-7 text-[#eaecef] sm:px-6 lg:px-8">
      <main className="mx-auto max-w-[1400px]">
        <header className="rounded-lg border border-[#272a33] bg-[#18191f] p-5 sm:p-6">
          <p className="font-mono text-xs text-[#9498a4]">면접 입장 · 기기 점검</p>
          <h1 className="mt-2 text-xl font-bold sm:text-2xl">실시간 화상 면접 준비</h1>
          <p className="mt-2 text-sm text-[#9498a4]">
            카메라와 마이크를 확인한 뒤 면접방에 입장해주세요.
          </p>
        </header>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.8fr)]">
          <div className="space-y-5">
            <section className="overflow-hidden rounded-lg border border-[#272a33] bg-[#18191f]">
              <LocalPreview
                videoTrack={videoTrack}
                audioTrack={audioTrack}
                className="aspect-video w-full"
              />
              <div className="flex flex-wrap items-center justify-between gap-2 p-4 text-xs">
                <span className={ready ? 'text-[#5FD6A5]' : 'text-[#ffe082]'}>
                  {ready ? '카메라 미리보기 준비됨' : '카메라 확인 중'}
                </span>
                <span className="text-[#9498a4]">내 화면은 좌우가 반전되어 표시됩니다.</span>
              </div>
            </section>

            <section className="rounded-lg border border-[#272a33] bg-[#18191f] p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-bold">입출력 장치 점검</h2>
                <span className="text-xs text-[#9498a4]">
                  {ready ? '기기 접근 허용됨' : '기기 접근 확인 필요'}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded border border-[#2e323c] bg-[#15161b] p-3">
                  <p className="text-[11px] text-[#9498a4]">카메라</p>
                  <p className="mt-1 truncate text-xs font-semibold">
                    {videoTrack?.label || '연결된 장치를 확인 중입니다'}
                  </p>
                </div>
                <div className="rounded border border-[#2e323c] bg-[#15161b] p-3">
                  <p className="text-[11px] text-[#9498a4]">마이크</p>
                  <p className="mt-1 truncate text-xs font-semibold">
                    {audioTrack?.label || '연결된 장치를 확인 중입니다'}
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs leading-5 text-[#9498a4]">
                말을 하면 영상 아래 마이크 막대가 움직입니다. 소리 테스트는 스피커 출력만
                확인합니다.
              </p>
              <button
                type="button"
                onClick={onSoundTest}
                className="mt-3 rounded border border-[#3f4452] bg-[#202229] px-3 py-2 text-xs hover:bg-[#282b34]"
              >
                소리 테스트
              </button>
              {soundNotice && (
                <p aria-live="polite" className="mt-2 text-xs text-[#c4c7c9]">
                  {soundNotice}
                </p>
              )}
            </section>
          </div>

          <aside className="rounded-lg border border-[#272a33] bg-[#18191f] p-5">
            <h2 className="text-sm font-bold">입장 전 확인</h2>
            <ol className="mt-4 space-y-3 text-xs leading-5 text-[#c4c7c9]">
              <li className="rounded border border-[#2e323c] bg-[#15161b] p-3">
                1. 카메라 화면에 본인이 보이는지 확인하세요.
              </li>
              <li className="rounded border border-[#2e323c] bg-[#15161b] p-3">
                2. 말할 때 마이크 막대가 움직이는지 확인하세요.
              </li>
              <li className="rounded border border-[#2e323c] bg-[#15161b] p-3">
                3. 필요하면 소리 테스트로 스피커를 확인하세요.
              </li>
            </ol>

            {guide ? (
              <div aria-live="polite" className="mt-5 rounded border border-amber-500/50 p-3">
                <p className="text-xs font-semibold text-[#ffe082]">{guide.title}</p>
                <p className="mt-1 text-xs leading-5 text-[#c4c7c9]">{guide.detail}</p>
                {errorName && (
                  <p className="mt-2 font-mono text-[10px] text-[#9498a4]">{errorName}</p>
                )}
              </div>
            ) : (
              <p className="mt-5 rounded border border-emerald-500/30 p-3 text-xs text-[#5FD6A5]">
                카메라와 마이크가 준비되었습니다.
              </p>
            )}
          </aside>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#272a33] bg-[#18191f] p-4">
          <p className="text-xs text-[#9498a4]">
            {ready
              ? '준비가 끝나면 면접방에 입장할 수 있습니다.'
              : '기기 권한을 확인한 뒤 입장할 수 있습니다.'}
          </p>
          <div className="flex w-full gap-2 sm:w-auto">
            <button
              type="button"
              onClick={onRetry}
              disabled={status === 'requesting' || starting}
              className="flex-1 rounded border border-[#3f4452] bg-[#202229] px-4 py-2.5 text-xs hover:bg-[#282b34] disabled:opacity-40 sm:flex-none"
            >
              기기 재점검
            </button>
            <button
              type="button"
              onMouseEnter={onPreload}
              onFocus={onPreload}
              onClick={onStart}
              disabled={!ready || starting}
              className="flex-1 rounded bg-[#2B44D6] px-5 py-2.5 text-xs font-semibold text-white hover:bg-[#243AB8] disabled:bg-[#30353f] disabled:text-[#9498a4] sm:flex-none"
            >
              {starting ? '면접방 연결 중' : '면접방 입장'}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
