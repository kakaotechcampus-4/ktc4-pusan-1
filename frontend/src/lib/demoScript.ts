/**
 * 최종 발표 데모 대본 — 무대에서 키를 누르면 나갈 「지원자 답변」들.
 *
 * 무대에는 지원자가 없다. 면접관(발표자)은 마이크로 **실제로** 질문하고, 그 질문은
 * 실제 STT 를 타고 자막에 오른다. 답변만 여기 있는 문장으로 대신한다 — BE 가 그것을
 * Agent 에 보내고, Agent 는 지원자 발화로 파이프라인에 넣는다. 그 뒤 자막 · 저장 ·
 * 꼬리질문 생성은 전부 실제 경로다.
 *
 * ⚠️ 이 모듈에는 `import.meta.env` 를 쓰지 않는다. `tests/*.test.mjs` 가
 * `src/lib/*.ts` 를 node 로 직접 불러오는데, 거기서는 `import.meta.env` 가 없어
 * 모듈이 터진다 (`interviewDelete.ts` 에 같은 주석이 있다). 켜짐 여부와 키 설정은
 * 부르는 훅이 넘겨준다.
 *
 * ## 대본이 지켜야 하는 조건
 *
 * AI 쪽 규칙에서 나온 것이라 지키지 않으면 **조용히** 아무 일도 안 일어난다.
 *
 * - **답변은 8어절 이상.** `MIN_ANSWER_WORDS = 8` 이고 세는 방법이
 *   `len(answer_text.split())` 다. 짧으면 자막만 뜨고 꼬리질문 라운드가 안 돈다.
 * - **발표자의 질문에 의문 어미가 있어야 한다.** `_QUESTION_MARKERS` 가
 *   `나요 · 까요 · 어떤 · 어떻게 · 왜 · 얼마나 · ?` 등을 본다. 그리고 공백·기호를
 *   뗀 길이가 10자를 넘어야 한다 — 짧으면 맞장구로 분류돼 버려진다.
 * - **답변에 구체적인 숫자나 고유명사를 둔다.** 꼬리질문은 답변에서 글자 그대로
 *   인용할 수 있는 것만 근거로 쓸 수 있고, 근거가 없으면 그 질문은 버려진다.
 *   「열심히 했습니다」 같은 답변에서는 아무것도 안 나온다.
 */

/** 기본 대본. 발표자료 데모 띠와 같은 시나리오(백엔드 · 초당 2만 건)에 맞춘다. */
export const DEFAULT_SCRIPT: readonly string[] = [
  '결제 API 를 맡아서 초당 2만 건까지 처리량을 올렸습니다. 처음에는 3천 건에서 응답이 밀렸습니다.',
  '읽기 쪽 커넥션 풀이 먼저 말랐습니다. 풀 크기를 20 에서 80 으로 올리고 읽기 전용 복제본을 두 대 붙였습니다.',
  '복제 지연이 평소 40밀리초인데 피크에 1.2초까지 벌어졌습니다. 그래서 결제 직후 조회만 주 DB 로 보내도록 나눴습니다.',
];

/** 대본을 덮어쓸 수 있는 자리. 발표 전날 다시 배포하지 않고 고치려고 둔다. */
export const SCRIPT_STORAGE_KEY = 'irya.demo.script';

/**
 * 대본을 쓸 세션 목록이 들어가는 자리.
 *
 * 이게 없으면 번들에 데모가 켜져 있는 동안 **그 배포의 모든 면접관**이 화살표를
 * 누르면 자기 면접에 대본이 들어간다. 화면에는 아무 표시도 없으니 알아차릴 수도
 * 없다. 그래서 세션을 적지 않으면 아무 데서도 동작하지 않게 둔다.
 *
 * 서버 쪽 `DEMO_INJECTION_SESSIONS` 와 같은 뜻이고, 서버가 최종 판정을 한다 —
 * 여기 적어도 서버 목록에 없으면 404 다. 이쪽은 평소 면접 화면이 키를 가로채는
 * 일(`preventDefault`)을 없애기 위한 것이다.
 *
 * 세션 id 는 데모 직전에 정해지므로 빌드에 넣을 수 없다. `localStorage` 에 둬서
 * 발표 전날 다시 배포하지 않고 넣을 수 있게 한다:
 *
 *     localStorage.setItem('irya.demo.sessions', JSON.stringify(['ses_abc']))
 */
export const SESSIONS_STORAGE_KEY = 'irya.demo.sessions';

/** 기본 전진 키. 발표자가 손에 익은 것으로 바꿀 수 있다. */
export const DEFAULT_ADVANCE_KEY = 'ArrowRight';

type Storage = Pick<globalThis.Storage, 'getItem'>;

/**
 * 쓸 대본. `localStorage` 에 올바른 모양이 있으면 그것, 없으면 기본 대본.
 *
 * 저장된 값이 깨져 있으면 **기본 대본으로 돌아간다.** 무대에서 빈 대본으로 조용히
 * 서 버리는 것이 가장 나쁜 결과라, 틀린 값은 무시하는 쪽을 고른다.
 */
export const readScript = (storage?: Storage | null): readonly string[] => {
  let raw: string | null;
  try {
    raw = storage?.getItem(SCRIPT_STORAGE_KEY) ?? null;
  } catch {
    // 사생활 보호 창 등에서 접근 자체가 던진다. 기본 대본으로 간다.
    return DEFAULT_SCRIPT;
  }
  if (raw === null) return DEFAULT_SCRIPT;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return DEFAULT_SCRIPT;
  }
  if (!Array.isArray(parsed)) return DEFAULT_SCRIPT;
  const lines = parsed
    .filter((line): line is string => typeof line === 'string')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  return lines.length > 0 ? lines : DEFAULT_SCRIPT;
};

/**
 * 대본을 쓸 세션들. 적혀 있지 않으면 빈 목록 — 아무 데서도 동작하지 않는다.
 *
 * 대본과 달리 **기본값으로 되돌리지 않는다.** 대본이 비면 데모가 안 되는 것뿐이지만,
 * 세션 목록이 비었을 때 「전부 허용」으로 떨어지면 실제 면접에 대본이 들어간다.
 */
export const readSessions = (storage?: Storage | null): readonly string[] => {
  let raw: string | null;
  try {
    raw = storage?.getItem(SESSIONS_STORAGE_KEY) ?? null;
  } catch {
    return [];
  }
  if (raw === null) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return splitSessionIds(raw);
  }
  // 서버 env 는 맨 쉼표 목록이라 `ses_abc` 하나를 그대로 넣기도 한다. JSON 으로는
  // 못 읽히거나(쉼표 목록) 문자열 하나로 읽힌다(`"ses_abc"`) — 둘 다 받는다.
  if (typeof parsed === 'string') return splitSessionIds(parsed);
  if (!Array.isArray(parsed)) return [];
  return parsed
    .filter((id): id is string => typeof id === 'string')
    .map((id) => id.trim())
    .filter((id) => id.length > 0);
};

/**
 * 쉼표 목록을 세션 id 들로. 둘러싼 대괄호·따옴표·공백을 떼어낸다.
 *
 * 서버 쪽(`DEMO_INJECTION_SESSIONS`)과 같은 규칙이다. 브라우저는 JSON 배열을,
 * 서버 env 는 맨 쉼표 목록을 받아서 둘을 바꿔 붙여넣는 실수가 나는데, 받아 주지
 * 않으면 아무것과도 안 맞는 id 한 개가 되어 **조용히** 안 켜진다.
 */
const splitSessionIds = (raw: string): string[] =>
  raw
    .split(',')
    .map((id) => id.replace(/^[[\]"'\s]+|[[\]"'\s]+$/g, ''))
    .filter((id) => id.length > 0);

export interface DemoActiveInput {
  /** 빌드에 데모가 켜져 있는지 (`VITE_DEMO_SCRIPT=on`). */
  enabled: boolean;
  role: 'INTERVIEWER' | 'CANDIDATE';
  sessionId: string;
  /** `readSessions` 가 읽은 목록. */
  sessions: readonly string[];
}

/**
 * 이 화면에서 대본을 써도 되는지. 셋 다 맞아야 한다.
 *
 * 지원자 화면에서는 애초에 주입할 수 없고(서버가 면접 주인만 받는다), 목록에 없는
 * 세션은 서버가 404 로 막는다. 그래도 여기서 먼저 끊는 이유는, 켜져 있으면 평소
 * 면접 화면이 화살표를 가로채기 때문이다.
 */
export const isDemoActive = ({ enabled, role, sessionId, sessions }: DemoActiveInput): boolean =>
  enabled && role === 'INTERVIEWER' && sessions.includes(sessionId);

/** 대본 한 줄이 꼬리질문 라운드를 돌릴 만한지. 8어절이 AI 쪽 하한이다. */
export const MIN_ANSWER_WORDS = 8;

export const wordCount = (line: string): number => line.trim().split(/\s+/).filter(Boolean).length;

/**
 * 대본에서 꼬리질문이 안 나올 줄들. 리허설 때 콘솔로 알려 주는 용도다.
 *
 * 막지는 않는다 — 짧은 답변도 자막에는 오르고, 그게 대본의 의도일 수 있다.
 */
export const shortLines = (script: readonly string[]): number[] =>
  script.map((line, i) => (wordCount(line) < MIN_ANSWER_WORDS ? i : -1)).filter((i) => i >= 0);

/**
 * 글자를 받는 곳에 포커스가 있는지.
 *
 * 면접 화면에는 메모 칸이 있다. 거기서 화살표로 커서를 옮기는 것이 대본을 넘기는
 * 일이 되면 안 된다.
 */
export const isTypingTarget = (target: EventTarget | null): boolean => {
  if (target === null) return false;
  // `HTMLElement` 가 없는 곳에서도 불린다 (node 로 돌리는 테스트). 그때 바로
  // `instanceof` 를 쓰면 「오른쪽이 객체가 아니다」로 던진다.
  const element = globalThis.HTMLElement;
  if (typeof element !== 'function' || !(target instanceof element)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
};

export interface AdvanceKeyEvent {
  key: string;
  repeat?: boolean;
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  target?: EventTarget | null;
}

/**
 * 이 입력이 「다음 답변」인지.
 *
 * 누른 키가 설정된 키와 같고, 보조키가 없고, 누른 채로 반복된 것이 아니고,
 * 글자를 받는 곳이 아닐 때만 참이다. 길게 누르면 대본이 한꺼번에 날아간다.
 */
export const isAdvanceKey = (
  event: AdvanceKeyEvent,
  advanceKey: string = DEFAULT_ADVANCE_KEY,
): boolean => {
  if (event.key !== advanceKey) return false;
  if (event.repeat) return false;
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false;
  return !isTypingTarget(event.target ?? null);
};

export interface ScriptCursor {
  /** 다음 줄을 꺼내고 한 칸 전진한다. 대본이 끝나면 `null`. */
  next: () => string | null;
  /** 아직 안 보낸 줄 수. 리허설에서 세어 보는 용도. */
  readonly remaining: number;
  /** 몇 줄을 보냈는지. */
  readonly sent: number;
  reset: () => void;
}

export const createScriptCursor = (script: readonly string[]): ScriptCursor => {
  let at = 0;
  return {
    next: () => (at < script.length ? (script[at++] ?? null) : null),
    get remaining() {
      return Math.max(0, script.length - at);
    },
    get sent() {
      return at;
    },
    reset: () => {
      at = 0;
    },
  };
};
