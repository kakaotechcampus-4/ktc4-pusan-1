/**
 * 카카오 콜백 (#126).
 *
 * 카카오가 `?code=...&state=...` 를 달고 이 주소로 돌려보낸다. 여기서 할 일은 셋이다.
 *   1. state 가 우리가 보낸 값인지 확인한다 (CSRF)
 *   2. code 를 BE 에 넘겨 우리 토큰으로 바꾼다
 *   3. 토큰을 저장하고 메인으로 보낸다
 *
 * 검사와 교환을 한 뮤테이션으로 묶었다. 이펙트에서 바로 setState 하면 렌더가 연쇄되고,
 * 실패 종류마다 상태를 따로 두면 화면이 어느 실패인지 흩어져 버린다.
 *
 * `code` 는 한 번만 쓸 수 있다. StrictMode 는 이펙트를 두 번 실행하므로 ref 로 막는다 —
 * 두 번째 호출은 반드시 401 로 실패한다.
 */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { kakaoLogin } from '../api/auth';
import { ApiError } from '../api/client';
import { saveAccessToken } from '../lib/authToken';
import { consumeKakaoState } from '../lib/kakao';
import { consumeLoginReturnTo } from '../lib/loginReturnTo';

type FailureKind = 'state' | 'denied' | 'expired' | 'kakao' | 'unknown';

const FAILURE: Record<FailureKind, { title: string; detail: string }> = {
  state: {
    title: '로그인을 이어갈 수 없습니다',
    detail: '요청이 우리 화면에서 시작된 것인지 확인하지 못했습니다. 처음부터 다시 시도해주세요.',
  },
  denied: {
    title: '카카오 로그인이 취소되었습니다',
    detail: '동의 화면에서 취소를 누르면 여기로 돌아옵니다.',
  },
  expired: {
    title: '인증 정보가 만료되었습니다',
    detail: '로그인 화면에서 다시 시도해주세요. 이미 사용한 링크로 들어와도 이 화면이 뜹니다.',
  },
  kakao: {
    title: '카카오 서버에 연결하지 못했습니다',
    detail: '잠시 후 다시 시도해주세요.',
  },
  unknown: {
    title: '로그인하지 못했습니다',
    detail: '잠시 후 다시 시도해주세요.',
  },
};

/** 콜백 자체가 잘못된 경우 — 서버에 묻기 전에 걸러진다. */
class CallbackError extends Error {
  readonly kind: FailureKind;
  constructor(kind: FailureKind) {
    super(kind);
    this.name = 'CallbackError';
    this.kind = kind;
  }
}

function toFailureKind(error: unknown): FailureKind {
  if (error instanceof CallbackError) return error.kind;
  if (error instanceof ApiError) {
    if (error.status === 401) return 'expired';
    if (error.status === 502) return 'kakao';
  }
  return 'unknown';
}

export default function KakaoCallbackPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const started = useRef(false);

  const exchange = useMutation({
    mutationFn: async () => {
      // 동의 화면에서 취소하면 code 없이 error 만 달려 돌아온다.
      if (params.get('error')) throw new CallbackError('denied');
      if (!consumeKakaoState(params.get('state'))) throw new CallbackError('state');

      const code = params.get('code');
      if (!code) throw new CallbackError('unknown');

      return kakaoLogin(code);
    },
    onSuccess: ({ accessToken }) => {
      // 카카오 로그인은 매번 인가 화면을 거치므로 "로그인 유지" 를 따로 묻지 않는다.
      saveAccessToken(accessToken, true);
      // replace 로 보낸다 — 뒤로 가기로 이 주소에 돌아오면 쓴 code 로 다시 시도하게 된다.
      void navigate(consumeLoginReturnTo(), { replace: true });
    },
  });

  const { mutate } = exchange;
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    mutate();
  }, [mutate]);

  const failure = exchange.isError ? FAILURE[toFailureKind(exchange.error)] : null;

  return (
    <div className="bg-surface flex min-h-full items-center justify-center p-8">
      <div className="border-border-base bg-surface-panel w-full max-w-md rounded-2xl border p-7 text-center">
        {failure ? (
          <>
            <span aria-hidden className="material-symbols-outlined text-[28px] text-[#FFC46B]">
              error
            </span>
            <h1 className="text-ink mt-3 text-lg font-semibold">{failure.title}</h1>
            <p className="text-ink-muted mt-2 text-[14px] leading-relaxed">{failure.detail}</p>
            <button
              type="button"
              onClick={() => void navigate('/login', { replace: true })}
              className="bg-brand mt-6 w-full rounded-xl py-3 text-[15px] font-medium text-white transition hover:bg-blue-700"
            >
              로그인 화면으로
            </button>
          </>
        ) : (
          <div aria-live="polite">
            <p className="text-ink text-[15px]">로그인하는 중입니다</p>
            <p className="text-ink-dim mt-1.5 text-[13px]">잠시만 기다려주세요.</p>
            <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/10">
              <div className="bg-brand h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
