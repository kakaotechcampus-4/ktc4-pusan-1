/**
 * 면접관 로그인 (S0)
 *
 * 카카오 인가 화면으로 보내는 것까지가 이 화면의 일이다. 돌아온 뒤 처리는
 * KakaoCallbackPage 가 맡는다.
 *
 * 비밀번호를 받지 않는다 — 우리가 저장하지 않으면 유출할 것도 없다.
 */

import { useMutation } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { kakaoLogin } from '../api/auth';
import loginVisual from '../assets/illustrations/login-visual.webp';
import { Logo } from '../components/ui/Logo';
import { saveAccessToken } from '../lib/authToken';
import { buildKakaoAuthorizeUrl, kakaoConfigured } from '../lib/kakao';
import { USE_MOCK_API } from '../mocks/mockApi';
import {
  consumeLoginReturnTo,
  readLoginReturnTo,
  rememberLoginReturnTo,
} from '../lib/loginReturnTo';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const rememberDestination = () =>
    rememberLoginReturnTo(location.state?.returnTo ?? readLoginReturnTo());

  /**
   * ⚠️ 목 로그인. 카카오 없이 화면을 둘러보기 위한 임시 입구다.
   *
   * 실제 로그인은 카카오 인가 화면을 거쳐야 하는데, 앱 키가 없거나 BE 가 떠 있지 않으면
   * 그 길이 막힌다. 목이 켜져 있을 때만 보인다 — BE 연동 시 이 블록과 목 핸들러를 함께 지운다.
   */
  const mockLogin = useMutation({
    mutationFn: () => {
      rememberDestination();
      return kakaoLogin('mock-code');
    },
    onSuccess: ({ accessToken }) => {
      saveAccessToken(accessToken, true);
      void navigate(consumeLoginReturnTo(), { replace: true });
    },
  });

  const start = () => {
    rememberDestination();
    // 같은 탭에서 떠난다. 새 창이면 팝업 차단에 걸리고, 돌아올 창을 찾기도 번거롭다.
    window.location.href = buildKakaoAuthorizeUrl();
  };

  return (
    <div className="bg-surface-panel grid min-h-full lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col px-5 py-6 sm:px-10">
        <Link to="/" aria-label="IRYA 홈" className="self-start">
          <Logo />
        </Link>

        <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <h1 className="text-ink text-[28px] font-bold tracking-tight">면접관 로그인</h1>
          <p className="text-ink-muted mt-2 text-[15px] leading-relaxed">
            면접을 만들고 기록을 검토하려면 로그인해주세요.
          </p>

          <button
            type="button"
            onClick={start}
            disabled={!kakaoConfigured}
            // 카카오 로그인 버튼 가이드의 색 · 심볼을 따른다.
            className="mt-8 flex h-13 w-full items-center justify-center gap-2.5 rounded-xl bg-[#FEE500] text-[15px] font-semibold text-black/85 transition-colors hover:bg-[#F2D900] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5 fill-black/85">
              <path d="M12 4C7.03 4 3 7.13 3 10.98c0 2.5 1.7 4.7 4.25 5.93l-1.08 3.97c-.1.35.3.63.6.43l4.73-3.13c.49.05.99.08 1.5.08 4.97 0 9-3.13 9-6.98S16.97 4 12 4Z" />
            </svg>
            카카오 로그인
          </button>

          {/* 자리를 미리 잡아 둔다. 문구가 뜰 때 버튼이 밀려 내려가면 두 번 누르게 된다. */}
          <div aria-live="polite" className="mt-3 min-h-[20px]">
            {!kakaoConfigured && (
              <p className="text-warning text-center text-[13px]">
                카카오 앱 키가 설정되지 않았습니다. <code>VITE_KAKAO_CLIENT_ID</code> 를 넣어주세요.
              </p>
            )}
          </div>

          {USE_MOCK_API && (
            <button
              type="button"
              onClick={() => mockLogin.mutate()}
              disabled={mockLogin.isPending}
              className="border-border-input text-ink-muted hover:bg-surface-bright w-full rounded-xl border border-dashed py-2.5 text-[13px] transition"
            >
              {mockLogin.isPending ? '들어가는 중…' : '목 데이터로 둘러보기 (개발용)'}
            </button>
          )}

          <div className="bg-surface border-border-base mt-8 flex gap-3 rounded-xl border p-4">
            <span aria-hidden className="material-symbols-outlined text-brand text-[20px]">
              info
            </span>
            <p className="text-ink-muted text-[13px] leading-relaxed">
              지원자는 로그인하지 않아도 됩니다. 받은 초대 링크를 열면 바로 입장합니다.
            </p>
          </div>

          <p className="text-ink-dim mt-6 text-[12px] leading-relaxed">
            로그인하면 카카오 닉네임과 프로필 사진을 받아오며,{' '}
            <Link to="/terms" className="text-ink-muted underline underline-offset-2">
              이용약관
            </Link>
            과{' '}
            <Link to="/privacy" className="text-ink-muted underline underline-offset-2">
              개인정보처리방침
            </Link>
            에 동의하는 것으로 봅니다.
          </p>
        </main>
      </div>

      {/* 넓은 화면에서만 보이는 장식. 정보는 없다. */}
      <aside
        aria-hidden
        className="from-brand-tint relative hidden overflow-hidden bg-gradient-to-br to-[#e9faf5] lg:block"
      >
        <img
          src={loginVisual}
          alt=""
          className="absolute inset-0 h-full w-full object-cover mix-blend-multiply"
        />
        <div className="absolute inset-x-0 bottom-0 p-12">
          <p className="text-ink text-[26px] leading-snug font-bold">
            면접은 사람이,
            <br />
            <span className="text-brand">정리는 AI가.</span>
          </p>
          <p className="text-ink-muted mt-2 text-[15px]">
            녹화 · 자막 · 근거가 한 화면에 이어집니다.
          </p>
        </div>
      </aside>
    </div>
  );
}
