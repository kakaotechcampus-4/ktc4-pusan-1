/**
 * 무대에서 대본을 넘기는 손 — 면접관이 키를 누르면 다음 답변을 주입한다.
 *
 * 키를 잡는 조건이 셋이다. 빌드에 `VITE_DEMO_SCRIPT=on` 이 들어 있고, 역할이
 * 면접관이고, **이 세션이 데모 세션으로 적혀 있을 때**다
 * (`localStorage['irya.demo.sessions']`). 하나라도 아니면 이벤트 리스너조차 붙지
 * 않는다 — 평소 면접 화면에 아무것도 더하지 않고, 화살표도 가로채지 않는다.
 *
 * 세 번째 조건이 없으면, 데모를 켜 둔 동안 그 배포의 모든 면접관이 화살표 한 번으로
 * 자기 면접에 대본을 넣게 된다. 화면에 표시가 없으니 알아차릴 수도 없다. 서버도
 * 같은 목록으로 한 번 더 막는다 (`DEMO_INJECTION_SESSIONS`).
 *
 * 화면에는 아무 표시도 하지 않는다. 데모의 요점이 「그냥 평소 화면이 돌고 있다」는
 * 것이라, 발표자용 표시가 떠 있으면 그걸 설명해야 한다. 발표자는 대본 순서를 외우고
 * 올라가고, 실패는 콘솔에 남는다.
 *
 * 판정과 대본 읽기는 `src/lib/demoScript.ts` 에 있다 — 그쪽은 `import.meta.env`
 * 없이 테스트할 수 있어야 해서 나눠 두었다.
 */

import { useEffect, useMemo, useRef } from 'react';
import { injectDemoUtterance } from '../api/demo';
import {
  DEFAULT_ADVANCE_KEY,
  createScriptCursor,
  isAdvanceKey,
  isDemoActive,
  readScript,
  readSessions,
  shortLines,
} from '../lib/demoScript';
import type { Role } from '../types/interview';

const ENABLED = import.meta.env.VITE_DEMO_SCRIPT === 'on';
const ADVANCE_KEY = import.meta.env.VITE_DEMO_SCRIPT_KEY?.trim() || DEFAULT_ADVANCE_KEY;

export interface UseDemoScriptOptions {
  sessionId: string;
  role: Role;
}

export function useDemoScript({ sessionId, role }: UseDemoScriptOptions): void {
  const active = useMemo(
    () =>
      ENABLED &&
      isDemoActive({
        enabled: ENABLED,
        role,
        sessionId,
        sessions: readSessions(globalThis.localStorage),
      }),
    [role, sessionId],
  );
  const script = useMemo(() => (active ? readScript(globalThis.localStorage) : []), [active]);
  // 보내는 중인지. 키를 두 번 빨리 누르면 두 줄이 겹쳐 나가므로 한 번에 하나만 보낸다.
  const sending = useRef(false);

  useEffect(() => {
    if (!active) return;
    const cursor = createScriptCursor(script);
    const short = shortLines(script);
    console.info(
      `[데모] 대본 ${script.length}줄 · 전진 키 ${ADVANCE_KEY}` +
        (short.length > 0 ? ` · 8어절 미만이라 꼬리질문이 안 나올 줄: ${short.join(', ')}` : ''),
    );

    const onKeyDown = (event: KeyboardEvent) => {
      if (!isAdvanceKey(event, ADVANCE_KEY)) return;
      if (sending.current) return;
      const line = cursor.next();
      if (line === null) {
        console.info('[데모] 대본이 끝났습니다.');
        return;
      }
      event.preventDefault();
      sending.current = true;
      injectDemoUtterance(sessionId, line)
        .then(() => {
          console.info(`[데모] ${cursor.sent}번째 답변을 넣었습니다. 남은 줄 ${cursor.remaining}`);
        })
        .catch((error: unknown) => {
          // 404 는 서버에서 꺼져 있거나 이 세션이 목록에 없는 것, 503 은 LiveKit 에
          // 전달하지 못한 것이다. 무대에서 할 수 있는 게 없으니 콘솔에만 남긴다.
          console.error('[데모] 답변을 넣지 못했습니다.', error);
        })
        .finally(() => {
          sending.current = false;
        });
    };

    globalThis.addEventListener('keydown', onKeyDown);
    return () => globalThis.removeEventListener('keydown', onKeyDown);
  }, [active, script, sessionId]);
}
