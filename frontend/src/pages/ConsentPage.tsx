/**
 * 지원자 동의 — 입장 전 첫 화면 (#245)
 *
 *   /interview/:sessionId   ← 입장(S0) 앞에 선다
 *
 * **동의를 받기 전에는 입장을 부르지 않는다.** 녹화는 방에 올라온 트랙에서
 * 시작하므로(BE `api/v1/webhooks.py`), 여기서 멈춰 있는 동안에는 지원자의 영상 ·
 * 음성이 한 조각도 올라가지 않는다. 서버도 같은 것을 막는다 — 동의가 없으면
 * `join` 이 403(CONSENT_REQUIRED) 이다. 화면만으로 막으면 이 화면을 거치지 않는
 * 길이 남는다.
 *
 * 문구는 `lib/consent.ts` 에 있다. 화면은 그것을 그리기만 한다 — 문구는 PM 이
 * 확인하는 글이라 고칠 자리가 한 곳이어야 한다.
 *
 * 면접관에게는 보여 주지 않는다. 동의는 녹화되는 사람에게 받는 것이다.
 */

import { useState, type ReactNode } from 'react';
import { useMutation } from '@tanstack/react-query';
import { agreeConsent } from '../api/interview';
import { buttonClass } from '../components/ui/buttonClass';
import { Logo } from '../components/ui/Logo';
import {
  CONSENT_AGREE_LABEL,
  CONSENT_DECLINED,
  CONSENT_LEAD,
  CONSENT_SECTIONS,
  CONSENT_TITLE,
  CONSENT_VERSION,
} from '../lib/consent';

export interface ConsentPageProps {
  sessionId: string;
  /** 동의를 서버에 남긴 뒤 다음 화면(입장)으로 넘긴다 */
  onAgreed: () => void;
}

export default function ConsentPage({ sessionId, onAgreed }: ConsentPageProps) {
  const [checked, setChecked] = useState(false);
  const [declined, setDeclined] = useState(false);

  const agree = useMutation({
    mutationFn: () => agreeConsent(sessionId, CONSENT_VERSION),
    onSuccess: onAgreed,
  });

  if (declined) {
    return (
      <Frame>
        <h1 className="text-ink text-[22px] font-bold tracking-tight">{CONSENT_DECLINED.title}</h1>
        <p className="text-ink-muted mt-3 text-[15px] leading-relaxed">{CONSENT_DECLINED.body}</p>
        <button
          type="button"
          onClick={() => setDeclined(false)}
          className={`${buttonClass('secondary', 'lg')} mt-6 w-full`}
        >
          {CONSENT_DECLINED.back}
        </button>
      </Frame>
    );
  }

  return (
    <Frame>
      <h1 className="text-ink text-[22px] font-bold tracking-tight">{CONSENT_TITLE}</h1>
      <p className="text-ink-muted mt-3 text-[15px] leading-relaxed">{CONSENT_LEAD}</p>

      {/* 읽어야 하는 글이라 왼쪽 정렬이다. 가운데로 맞추면 줄 머리가 흔들려 읽기 어렵다 */}
      <div className="mt-6 flex flex-col gap-5 text-left">
        {CONSENT_SECTIONS.map((section) => (
          <section key={section.title}>
            <h2 className="text-ink text-[15px] font-semibold">{section.title}</h2>
            <ul className="mt-2 flex flex-col gap-1.5">
              {section.items.map((item) => (
                <li key={item} className="text-ink-muted flex gap-2 text-[14px] leading-relaxed">
                  <span aria-hidden className="text-brand">
                    ·
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      {/* 체크 없이는 입장 버튼이 열리지 않는다. 읽었다는 표시가 곧 동의다 */}
      <label className="border-border-base bg-surface-container mt-6 flex items-start gap-3 rounded-2xl border p-4 text-left">
        <input
          type="checkbox"
          disabled={agree.isPending}
          checked={checked}
          onChange={(e) => setChecked(e.target.checked)}
          className="accent-brand mt-0.5 h-5 w-5 shrink-0"
        />
        <span className="text-ink text-[14px] leading-relaxed font-medium">
          {CONSENT_AGREE_LABEL}
        </span>
      </label>

      <div aria-live="polite" className="mt-4 min-h-[24px]">
        {agree.isError && (
          <p className="bg-danger-tint text-danger rounded-xl px-4 py-3 text-[14px]">
            동의를 저장하지 못했습니다. 잠시 후 다시 눌러주세요.
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={() => agree.mutate()}
        disabled={!checked || agree.isPending}
        className={`${buttonClass('primary', 'lg')} w-full`}
      >
        {agree.isPending ? '저장하는 중…' : '동의하고 입장'}
      </button>
      <button
        type="button"
        disabled={agree.isPending}
        onClick={() => setDeclined(true)}
        className="text-ink-dim mt-3 w-full text-[14px] underline underline-offset-4"
      >
        동의하지 않습니다
      </button>
    </Frame>
  );
}

/** 로그인 없이 여는 화면이라 앱 틀 없이 가운데 카드 하나로 그린다 (`JoinPage` 와 같다). */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="from-brand-tint via-surface flex min-h-full flex-col items-center justify-center gap-6 bg-gradient-to-b to-[#effbf8] p-5">
      <Logo />
      <main className="border-border-base bg-surface-panel shadow-card w-full max-w-xl rounded-3xl border p-7 text-center sm:p-8">
        {children}
      </main>
    </div>
  );
}
