/**
 * 진입 — 방 코드 입력 (S0)
 *
 * `?code=ABCD1234` 로 들어오면 입력란이 채워진다. 링크로 받은 사람과
 * 코드를 구두로 받은 사람이 같은 화면을 쓴다 (issue #9).
 *
 * 여기서는 코드만 확인한다. 카메라·마이크 권한은 다음 단계(기기 점검)에서 묻는다 —
 * 틀린 코드가 권한 프롬프트보다 먼저 걸려야 하기 때문이다.
 */

import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { joinSession, toJoinFailure } from '../api/interview';
import {
  CODE_LENGTH,
  formatCode,
  isValidCode,
  normalizeCode,
  rejectedChars,
} from '../lib/roomCode';
import type { JoinFailure, JoinSessionResponse } from '../types/interview';

const FAILURE_MESSAGE: Record<JoinFailure, string> = {
  'not-found': '없는 코드입니다. 다시 확인해주세요.',
  expired: '만료된 코드입니다. 면접관에게 새 코드를 요청해주세요.',
  ended: '이미 종료된 면접입니다.',
  full: '이미 두 명이 입장해 있어 들어갈 수 없습니다.',
  failed: '입장하지 못했습니다. 잠시 후 다시 시도해주세요.',
};

export interface JoinPageProps {
  /** 입장 성공 — 다음은 기기 점검 화면이다 */
  onJoined: (session: JoinSessionResponse) => void;
}

export default function JoinPage({ onJoined }: JoinPageProps) {
  const [searchParams] = useSearchParams();
  // 링크로 들어온 코드는 초기값으로만 읽는다. 이후 URL 이 바뀌어도
  // 사용자가 입력 중인 값을 덮어쓰지 않는다.
  const [code, setCode] = useState(() =>
    normalizeCode(searchParams.get('code') ?? '').slice(0, CODE_LENGTH),
  );
  const [failure, setFailure] = useState<JoinFailure | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const valid = isValidCode(code);
  // 허용되지 않는 문자를 눌렀을 때만 안내한다. 짧은 건 아직 입력 중이므로 조용히 둔다.
  const rejected = rejectedChars(code);

  const handleChange = (raw: string) => {
    setFailure(null);
    // 허용 문자만 남기고 8자에서 끊는다. 붙여넣기로 긴 문자열이 와도 안전하다.
    const next = normalizeCode(raw)
      .split('')
      .filter((ch) => /[A-Z0-9]/.test(ch))
      .join('')
      .slice(0, CODE_LENGTH);
    setCode(next);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || submitting) return;

    setSubmitting(true);
    setFailure(null);
    try {
      onJoined(await joinSession(code));
    } catch (err) {
      setFailure(toJoinFailure(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-[#0B0E14] p-8">
      <form onSubmit={(e) => void handleSubmit(e)} className="w-full max-w-md">
        <h1 className="text-2xl font-semibold text-white">면접 입장</h1>
        <p className="mt-2 text-[15px] text-white/60">받으신 8자리 코드를 입력해주세요.</p>

        <label htmlFor="room-code" className="sr-only">
          방 코드
        </label>
        <input
          id="room-code"
          value={formatCode(code)}
          onChange={(e) => handleChange(e.target.value)}
          placeholder="ABCD-EFGH"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          inputMode="text"
          aria-invalid={failure !== null}
          aria-describedby={failure || rejected.length > 0 ? 'room-code-error' : undefined}
          className="mt-7 w-full rounded-xl bg-white/[0.07] px-5 py-4 text-center font-mono text-2xl tracking-[0.2em] text-white placeholder:text-white/25 focus:ring-2 focus:ring-[#2B44D6] focus:outline-none"
        />

        <div id="room-code-error" aria-live="polite" className="mt-3 min-h-[20px]">
          {failure && <p className="text-sm text-[#FF8A8A]">{FAILURE_MESSAGE[failure]}</p>}
          {!failure && rejected.length > 0 && (
            <p className="text-sm text-[#FFC46B]">
              {rejected.join(', ')} 은(는) 코드에 쓰이지 않습니다. O·I·L·0·1 은 헷갈려서
              제외했습니다.
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={!valid || submitting}
          className="mt-4 w-full rounded-lg bg-[#2B44D6] py-3.5 text-[15px] font-medium text-white transition hover:bg-[#243AB8] disabled:bg-white/10 disabled:text-white/35"
        >
          {submitting ? '입장하는 중…' : '입장'}
        </button>

        <p className="mt-6 text-center text-[13px] text-white/35">
          코드는 면접관이 발급합니다. 링크를 받으셨다면 그대로 열어주세요.
        </p>
      </form>
    </div>
  );
}
