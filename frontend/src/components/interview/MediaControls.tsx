export interface MediaControlsProps {
  microphone: boolean;
  camera: boolean;
  speaker: boolean;
  busy: boolean;
  enabled: boolean;
  onToggle: (kind: 'microphone' | 'camera' | 'speaker') => void;
}

export function MediaControls({
  microphone,
  camera,
  speaker,
  busy,
  enabled,
  onToggle,
}: MediaControlsProps) {
  return (
    <div className="group absolute inset-x-0 bottom-0 z-20 flex justify-center px-3 pt-6 pb-[max(1rem,env(safe-area-inset-bottom))]">
      <div
        className="glass interview-readable flex max-w-full flex-wrap justify-center gap-2 rounded-2xl p-2 transition-opacity md:opacity-70 md:group-hover:opacity-100 md:focus-within:opacity-100"
        role="group"
        aria-label="통화 조작"
      >
        {(
          [
            ['microphone', microphone, '마이크'],
            ['camera', camera, '카메라'],
            ['speaker', speaker, '상대 소리'],
          ] as const
        ).map(([kind, on, label]) => (
          <button
            key={kind}
            type="button"
            disabled={busy || !enabled}
            aria-pressed={on}
            onClick={() => onToggle(kind)}
            className={`min-h-11 rounded-xl px-3 text-sm font-semibold disabled:opacity-50 ${on ? 'bg-white/10 text-white' : 'bg-danger-tint text-danger ring-danger/50 ring-1'}`}
            aria-label={`${label} ${on ? '끄기' : '켜기'}`}
          >
            {label} {on ? '켜짐' : '꺼짐'}
          </button>
        ))}
      </div>
    </div>
  );
}
