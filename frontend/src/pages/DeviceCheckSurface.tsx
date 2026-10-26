import { LocalPreview } from '../components/interview/LocalPreview';
import type { PermissionStatus } from '../hooks/usePermissionCheck';
import { Link } from 'react-router-dom';
import deviceCheckImg from '../assets/illustrations/device-check.webp';
import { Badge } from '../components/ui/Badge';
import { buttonClass } from '../components/ui/buttonClass';
import { Logo } from '../components/ui/Logo';

interface DeviceCheckSurfaceProps {
  onBack?: () => void;
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
  onBack,
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
    <div className="bg-surface min-h-full px-4 py-6 sm:px-6 lg:px-8">
      <main className="mx-auto max-w-[1200px]">
        <header className="flex flex-wrap items-center gap-3">
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              aria-label="입장 화면으로"
              className="text-ink-muted hover:bg-surface-bright hover:text-ink -ml-2 rounded-lg p-2"
            >
              <span aria-hidden className="material-symbols-outlined text-[22px]">
                arrow_back
              </span>
            </button>
          ) : (
            <Link to="/" aria-label="IRYA 홈">
              <Logo size="sm" />
            </Link>
          )}
          <div className="min-w-0 flex-1">
            <h1 className="text-ink text-[22px] font-bold tracking-tight">기기 점검</h1>
            <p className="text-ink-muted text-[14px]">
              카메라와 마이크를 확인한 뒤 면접방에 입장해주세요.
            </p>
          </div>
          <Badge tone={ready ? 'accent' : 'warning'}>{ready ? '준비됨' : '확인 중'}</Badge>
        </header>

        <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.8fr)]">
          <div className="flex flex-col gap-5">
            <section className="border-border-base bg-surface-panel shadow-card overflow-hidden rounded-2xl border">
              <LocalPreview
                videoTrack={videoTrack}
                audioTrack={audioTrack}
                className="aspect-video w-full"
              />
              <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5 text-[13px]">
                <span
                  className={`inline-flex items-center gap-1.5 font-semibold ${ready ? 'text-accent-strong' : 'text-warning'}`}
                >
                  <span aria-hidden className="material-symbols-outlined text-[18px]">
                    {ready ? 'check_circle' : 'pending'}
                  </span>
                  {ready ? '카메라 미리보기 준비됨' : '카메라 확인 중'}
                </span>
                <span className="text-ink-dim">내 화면은 좌우가 반전되어 표시됩니다.</span>
              </div>
            </section>

            <section className="border-border-base bg-surface-panel shadow-card rounded-2xl border p-5">
              <h2 className="text-ink text-[16px] font-semibold">입출력 장치</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Device icon="videocam" label="카메라" name={videoTrack?.label} />
                <Device icon="mic" label="마이크" name={audioTrack?.label} />
              </div>
              <p className="text-ink-muted mt-4 text-[13px] leading-relaxed">
                말을 하면 영상 아래 마이크 막대가 움직입니다. 소리 테스트는 스피커 출력만
                확인합니다.
              </p>
              <button
                type="button"
                onClick={onSoundTest}
                className={`${buttonClass('secondary', 'sm')} mt-3`}
              >
                <span aria-hidden className="material-symbols-outlined text-[18px]">
                  volume_up
                </span>
                소리 테스트
              </button>
              {soundNotice && (
                <p aria-live="polite" className="text-ink-muted mt-2 text-[13px]">
                  {soundNotice}
                </p>
              )}
            </section>
          </div>

          <aside className="border-border-base bg-surface-panel shadow-card self-start rounded-2xl border p-5">
            <img
              src={deviceCheckImg}
              alt=""
              width={1200}
              height={800}
              className="mx-auto -mt-1 w-full max-w-[260px]"
            />
            <h2 className="text-ink mt-2 text-[16px] font-semibold">입장 전 확인</h2>
            <ol className="text-ink-muted mt-3 flex flex-col gap-2.5 text-[14px] leading-relaxed">
              {[
                '카메라 화면에 본인이 보이는지 확인하세요.',
                '말할 때 마이크 막대가 움직이는지 확인하세요.',
                '필요하면 소리 테스트로 스피커를 확인하세요.',
              ].map((text, i) => (
                <li key={text} className="flex gap-3">
                  <span className="bg-brand-tint text-brand flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-bold">
                    {i + 1}
                  </span>
                  {text}
                </li>
              ))}
            </ol>

            {guide ? (
              <div aria-live="polite" className="bg-warning-tint mt-5 rounded-xl p-4">
                <p className="text-warning text-[14px] font-semibold">{guide.title}</p>
                <p className="text-ink-muted mt-1 text-[13px] leading-relaxed">{guide.detail}</p>
                {errorName && (
                  <p className="text-ink-dim mt-2 font-mono text-[11px]">{errorName}</p>
                )}
              </div>
            ) : (
              <p className="bg-accent-tint text-accent-strong mt-5 rounded-xl p-4 text-[14px] font-semibold">
                카메라와 마이크가 준비되었습니다.
              </p>
            )}
          </aside>
        </div>

        <div className="border-border-base bg-surface-panel shadow-card mt-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border p-4">
          <p className="text-ink-muted text-[14px]">
            {ready
              ? '준비가 끝나면 면접방에 입장할 수 있습니다.'
              : '기기 권한을 확인한 뒤 입장할 수 있습니다.'}
          </p>
          <div className="flex w-full gap-2 sm:w-auto">
            <button
              type="button"
              onClick={onRetry}
              disabled={status === 'requesting' || starting}
              className={`${buttonClass('secondary')} flex-1 sm:flex-none`}
            >
              기기 재점검
            </button>
            <button
              type="button"
              onMouseEnter={onPreload}
              onFocus={onPreload}
              onClick={onStart}
              disabled={!ready || starting}
              className={`${buttonClass('primary')} flex-1 sm:flex-none`}
            >
              {starting ? '면접방 연결 중…' : '면접방 입장'}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

function Device({ icon, label, name }: { icon: string; label: string; name?: string }) {
  return (
    <div className="bg-surface-container flex items-center gap-3 rounded-xl p-3.5">
      <span
        aria-hidden
        className="material-symbols-outlined bg-surface-panel text-brand rounded-lg p-1.5 text-[20px]"
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-ink-dim text-[12px]">{label}</p>
        <p className="text-ink truncate text-[14px] font-medium">
          {name || '연결된 장치를 확인 중입니다'}
        </p>
      </div>
    </div>
  );
}
