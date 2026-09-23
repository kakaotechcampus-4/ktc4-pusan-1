/**
 * 면접관 로그인 (S0)
 *
 * 아이디·비밀번호로 토큰을 받아 저장하고 첫 화면으로 보낸다.
 *
 * ⚠️ BE 에 인증 API 가 없다. 경로(POST /api/v1/auth/login)만 정해 두고 목으로 동작한다.
 * 시안의 소셜 로그인·엔진 상태 배너·보안 인증 문구·비밀번호 찾기는 뒷단이 없어 넣지 않았다.
 */

import { useMutation } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../api/auth';
import { ApiError } from '../api/client';
import { saveAccessToken } from '../lib/authToken';

export default function LoginPage() {
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  // 비밀번호를 가려 두면 오타를 찾을 수 없다. 눈으로 확인할 길을 열어 둔다.
  const [revealed, setRevealed] = useState(false);
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => login({ email: email.trim(), password }),
    onSuccess: ({ accessToken }) => {
      saveAccessToken(accessToken, keepSignedIn);
      // 뒤로 가기로 로그인 화면에 돌아오지 않게 한다 — 이미 들어온 뒤에는 볼 일이 없다.
      void navigate('/', { replace: true });
    },
    onError: (e) =>
      setError(
        e instanceof ApiError && e.status === 401
          ? '아이디 또는 비밀번호가 올바르지 않습니다.'
          : '로그인하지 못했습니다. 잠시 후 다시 시도해주세요.',
      ),
  });

  const pending = submit.isPending;

  return (
    <div className="bg-surface relative flex min-h-full items-center justify-center overflow-hidden p-4 md:p-8">
      {/* 시안의 배경 광원. 정보는 없고 카드가 떠 보이게 하는 장식이다. */}
      <div
        aria-hidden
        className="bg-brand/10 pointer-events-none fixed top-1/4 left-1/2 h-[450px] w-[650px] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none fixed top-1/3 left-1/3 h-[380px] w-[380px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-500/10 blur-[100px]"
      />

      <div className="relative w-full max-w-md">
        <div className="border-border-base bg-surface-panel relative overflow-hidden rounded-2xl border p-6 shadow-2xl shadow-black/60 md:p-9">
          {/* 카드 상단의 얇은 광택 */}
          <div
            aria-hidden
            className="via-brand-soft/40 absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent to-transparent"
          />

          <div className="mb-7 flex flex-col items-center text-center">
            <span
              aria-hidden
              className="border-brand-soft/30 bg-brand shadow-brand/30 mb-3 flex h-12 w-12 items-center justify-center rounded-xl border text-white shadow-lg"
            >
              <span className="material-symbols-outlined text-[26px]">record_voice_over</span>
            </span>
            <span className="text-ink text-lg font-bold tracking-tight">IRYA</span>
            <h1 className="text-ink pt-2 text-2xl font-bold tracking-tight">면접관 로그인</h1>
            <p className="text-ink-muted mt-2 text-sm">
              AI 면접 진행과 기록 열람을 위한 계정입니다.
            </p>
          </div>

          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              setError(null);
              if (!email.trim() || !password) {
                setError('아이디와 비밀번호를 모두 입력해주세요.');
                return;
              }
              submit.mutate();
            }}
          >
            <Field htmlFor="email" label="아이디 (이메일)" icon="mail">
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="recruiter@company.com"
                disabled={pending}
                className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim hover:border-ink-dim focus:border-brand focus:ring-brand/40 w-full rounded-xl border py-2.5 pr-4 pl-10 text-sm transition-colors outline-none focus:ring-2 disabled:opacity-60"
              />
            </Field>

            <Field htmlFor="password" label="비밀번호" icon="lock">
              <input
                id="password"
                name="password"
                type={revealed ? 'text' : 'password'}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={pending}
                className="border-border-input bg-surface-input text-ink placeholder:text-ink-dim hover:border-ink-dim focus:border-brand focus:ring-brand/40 w-full rounded-xl border py-2.5 pr-11 pl-10 text-sm transition-colors outline-none focus:ring-2 disabled:opacity-60"
              />
              <button
                type="button"
                onClick={() => setRevealed((v) => !v)}
                aria-label={revealed ? '비밀번호 숨기기' : '비밀번호 표시'}
                className="text-ink-dim hover:text-ink-muted absolute inset-y-0 right-0 flex items-center pr-3.5 transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">
                  {revealed ? 'visibility_off' : 'visibility'}
                </span>
              </button>
            </Field>

            <label className="flex cursor-pointer items-center gap-2 select-none">
              <input
                type="checkbox"
                checked={keepSignedIn}
                onChange={(e) => setKeepSignedIn(e.target.checked)}
                className="border-border-input bg-surface-input checked:border-brand checked:bg-brand h-4 w-4 shrink-0 appearance-none rounded border transition-colors"
              />
              <span className="text-ink-muted text-xs">로그인 상태 유지</span>
            </label>

            <button
              type="submit"
              disabled={pending}
              className="border-brand-soft/20 bg-brand shadow-brand/20 disabled:bg-surface-bright disabled:text-ink-dim mt-1 flex w-full items-center justify-center gap-2 rounded-xl border py-3 text-sm font-semibold text-white shadow-lg transition-colors hover:bg-[#1d4ed8] disabled:shadow-none"
            >
              <span>{pending ? '로그인 중…' : '로그인'}</span>
              {!pending && <span className="material-symbols-outlined text-[18px]">east</span>}
            </button>
          </form>

          {/* 자리를 미리 잡아 둔다. 문구가 뜰 때 버튼이 밀려 내려가면 두 번 누르게 된다. */}
          <div aria-live="polite" className="mt-3 min-h-[20px]">
            {error && <p className="text-center text-[13px] text-[#FFC46B]">{error}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 라벨 + 아이콘이 붙은 입력 한 칸. 아이콘은 입력칸 안쪽 왼쪽에 겹쳐 놓는다. */
function Field({
  htmlFor,
  label,
  icon,
  children,
}: {
  htmlFor: string;
  label: string;
  /** Material Symbols 이름 */
  icon: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-ink-muted text-xs font-semibold">
        {label}
      </label>
      <div className="relative">
        <span
          aria-hidden
          className="text-ink-dim pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5"
        >
          <span className="material-symbols-outlined text-[18px]">{icon}</span>
        </span>
        {children}
      </div>
    </div>
  );
}
