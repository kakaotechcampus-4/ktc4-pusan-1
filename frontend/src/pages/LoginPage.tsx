/**
 * 면접관 로그인 (S0)
 *
 * 카카오 인가 화면으로 보내는 것까지가 이 화면의 일이다. 돌아온 뒤 처리는
 * KakaoCallbackPage 가 맡는다.
 *
 * 비밀번호를 받지 않는다 — 우리가 저장하지 않으면 유출할 것도 없다.
 */

import { useMutation } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { kakaoLogin } from '../api/auth';
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
            <p className="text-ink-muted mt-2 text-sm leading-relaxed">
              AI 면접 진행과 기록 열람을 위한 계정입니다.
              <br />
              지원자는 받은 초대 링크로 바로 입장합니다.
            </p>
          </div>

          <button
            type="button"
            onClick={start}
            disabled={!kakaoConfigured}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#FEE500] py-3.5 text-sm font-semibold text-[#191600] transition-colors hover:bg-[#F2D900] disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-white/35"
          >
            <span aria-hidden className="material-symbols-outlined text-[20px]">
              chat_bubble
            </span>
            카카오 계정으로 로그인
          </button>

          {/* 자리를 미리 잡아 둔다. 문구가 뜰 때 버튼이 밀려 내려가면 두 번 누르게 된다. */}
          <div aria-live="polite" className="mt-3 min-h-[20px]">
            {!kakaoConfigured && (
              <p className="text-center text-[13px] text-[#FFC46B]">
                카카오 앱 키가 설정되지 않았습니다. <code>VITE_KAKAO_CLIENT_ID</code> 를 넣어주세요.
              </p>
            )}
          </div>

          <p className="text-ink-dim mt-6 text-center text-[12px] leading-relaxed">
            로그인하면 카카오 닉네임과 프로필 사진을 받아옵니다.
          </p>

          {USE_MOCK_API && (
            <button
              type="button"
              onClick={() => mockLogin.mutate()}
              disabled={mockLogin.isPending}
              className="border-border-base text-ink-muted hover:bg-surface-bright mt-4 w-full rounded-xl border border-dashed py-2.5 text-[13px] transition"
            >
              {mockLogin.isPending ? '들어가는 중…' : '목 데이터로 둘러보기 (개발용)'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
