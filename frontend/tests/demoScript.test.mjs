import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DEFAULT_ADVANCE_KEY,
  DEFAULT_SCRIPT,
  MIN_ANSWER_WORDS,
  SCRIPT_STORAGE_KEY,
  createScriptCursor,
  isAdvanceKey,
  isDemoActive,
  readScript,
  readSessions,
  shortLines,
  wordCount,
} from '../src/lib/demoScript.ts';

const storageWith = (value) => ({ getItem: () => value });

test('기본 대본은 전부 8어절 이상이다 — 미만이면 꼬리질문이 안 나온다', () => {
  assert.deepEqual(shortLines(DEFAULT_SCRIPT), []);
  for (const line of DEFAULT_SCRIPT) {
    assert.ok(wordCount(line) >= MIN_ANSWER_WORDS, line);
  }
});

test('기본 대본의 각 줄에는 인용할 수 있는 숫자가 있다', () => {
  // 근거로 인용할 것이 없으면 꼬리질문이 생성돼도 접지 검사에서 버려진다.
  for (const line of DEFAULT_SCRIPT) {
    assert.match(line, /\d/, line);
  }
});

test('저장된 대본이 있으면 그것을 쓴다', () => {
  const saved = ['첫 줄입니다.', '둘째 줄입니다.'];
  assert.deepEqual(readScript(storageWith(JSON.stringify(saved))), saved);
});

test('저장된 대본의 빈 줄과 문자열 아닌 항목은 버린다', () => {
  const stored = JSON.stringify(['쓸 줄입니다.', '   ', 42, null, '또 쓸 줄입니다.']);
  assert.deepEqual(readScript(storageWith(stored)), ['쓸 줄입니다.', '또 쓸 줄입니다.']);
});

test('저장된 값이 깨져 있으면 기본 대본으로 돌아간다', () => {
  for (const broken of ['{', '"문자열"', '{"a":1}', '[]', '[""]', '[1,2,3]']) {
    assert.deepEqual(readScript(storageWith(broken)), DEFAULT_SCRIPT, broken);
  }
});

test('저장소가 없거나 접근이 막혀도 기본 대본이 나온다', () => {
  assert.deepEqual(readScript(null), DEFAULT_SCRIPT);
  assert.deepEqual(readScript(undefined), DEFAULT_SCRIPT);
  assert.deepEqual(
    readScript({
      getItem: () => {
        throw new Error('사생활 보호 창');
      },
    }),
    DEFAULT_SCRIPT,
  );
});

test('저장소 키는 바뀌지 않는다 — 발표 전날 손으로 넣는 값이다', () => {
  assert.equal(SCRIPT_STORAGE_KEY, 'irya.demo.script');
});

test('커서는 한 줄씩 꺼내고 끝나면 null 을 준다', () => {
  const cursor = createScriptCursor(['하나', '둘']);
  assert.equal(cursor.remaining, 2);
  assert.equal(cursor.next(), '하나');
  assert.equal(cursor.sent, 1);
  assert.equal(cursor.next(), '둘');
  assert.equal(cursor.remaining, 0);
  assert.equal(cursor.next(), null);
  assert.equal(cursor.next(), null);
  cursor.reset();
  assert.equal(cursor.next(), '하나');
});

test('설정된 키만 대본을 넘긴다', () => {
  assert.ok(isAdvanceKey({ key: DEFAULT_ADVANCE_KEY }));
  assert.ok(!isAdvanceKey({ key: 'ArrowLeft' }));
  assert.ok(isAdvanceKey({ key: 'F8' }, 'F8'));
  assert.ok(!isAdvanceKey({ key: DEFAULT_ADVANCE_KEY }, 'F8'));
});

test('길게 눌러도 한 줄씩만 — repeat 는 무시한다', () => {
  assert.ok(!isAdvanceKey({ key: DEFAULT_ADVANCE_KEY, repeat: true }));
});

test('보조키가 눌려 있으면 넘기지 않는다', () => {
  for (const modifier of ['altKey', 'ctrlKey', 'metaKey', 'shiftKey']) {
    assert.ok(!isAdvanceKey({ key: DEFAULT_ADVANCE_KEY, [modifier]: true }), modifier);
  }
});

test('메모 칸에서 화살표를 누르는 것은 대본을 넘기는 것이 아니다', () => {
  // 면접 화면에 메모 칸이 있다. 거기서 커서를 옮기다가 답변이 나가면 안 된다.
  class FakeElement {
    constructor(tagName, isContentEditable = false) {
      this.tagName = tagName;
      this.isContentEditable = isContentEditable;
    }
  }
  const previous = globalThis.HTMLElement;
  globalThis.HTMLElement = FakeElement;
  try {
    for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) {
      const target = new FakeElement(tag);
      assert.ok(!isAdvanceKey({ key: DEFAULT_ADVANCE_KEY, target }), tag);
    }
    const editable = new FakeElement('DIV', true);
    assert.ok(!isAdvanceKey({ key: DEFAULT_ADVANCE_KEY, target: editable }));
    const plain = new FakeElement('DIV');
    assert.ok(isAdvanceKey({ key: DEFAULT_ADVANCE_KEY, target: plain }));
  } finally {
    globalThis.HTMLElement = previous;
  }
});

// ── 어느 세션에서 켜지는가 ────────────────────────────────

const sessionsIn = (value) => ({ getItem: () => value });

test('세션 목록이 적혀 있지 않으면 빈 목록이다 — 전부 허용으로 떨어지지 않는다', () => {
  assert.deepEqual(readSessions(sessionsIn(null)), []);
  assert.deepEqual(readSessions(null), []);
  assert.deepEqual(readSessions(undefined), []);
  assert.deepEqual(
    readSessions({
      getItem: () => {
        throw new Error('사생활 보호 창');
      },
    }),
    [],
  );
});

// BE·AI 쪽 `SESSION_LIST_CASES` 와 같은 목록이다. 세 쪽이 같은 입력을 같게 읽어야
// 리허설에서 「서버에는 들어갔는데 화면은 안 켜진다」로 헤매지 않는다.
const SESSION_LIST_CASES = [
  ['', []],
  ['   ', []],
  [',,', []],
  ['ses_a', ['ses_a']],
  [' ses_a , ses_b ', ['ses_a', 'ses_b']],
  ['["ses_a","ses_b"]', ['ses_a', 'ses_b']],
  ['["ses_a"]', ['ses_a']],
  ["['ses_a']", ['ses_a']],
  ['"ses_a"', ['ses_a']],
  ['*', ['*']],
  ['all', ['all']],
  ['ses_a;ses_b', ['ses_a;ses_b']],
];

test('세션 목록을 서버와 같은 규칙으로 읽는다 — JSON 배열이든 쉼표든', () => {
  for (const [raw, expected] of SESSION_LIST_CASES) {
    assert.deepEqual(readSessions(sessionsIn(raw)), expected, JSON.stringify(raw));
  }
});

test('세션 목록의 쓸모없는 항목은 버린다', () => {
  assert.deepEqual(readSessions(sessionsIn('[" ses_a ", "", 42, null]')), ['ses_a']);
  assert.deepEqual(readSessions(sessionsIn('{"a":1}')), []);
});

test('빌드 · 역할 · 세션 셋이 다 맞아야 켜진다', () => {
  const base = { enabled: true, role: 'INTERVIEWER', sessionId: 'ses_a', sessions: ['ses_a'] };
  assert.ok(isDemoActive(base));
  assert.ok(!isDemoActive({ ...base, enabled: false }), '빌드에 꺼져 있으면 안 된다');
  assert.ok(!isDemoActive({ ...base, role: 'CANDIDATE' }), '지원자 화면에서는 안 된다');
});

test('목록에 없는 세션에서는 켜지지 않는다 — 평소 면접이 화살표를 잃지 않는다', () => {
  // 이게 리뷰가 잡은 것이다. 켜 둔 동안 그 배포의 모든 면접관이 영향을 받았다.
  const base = { enabled: true, role: 'INTERVIEWER', sessionId: 'ses_real_interview' };
  assert.ok(!isDemoActive({ ...base, sessions: [] }));
  assert.ok(!isDemoActive({ ...base, sessions: ['ses_demo'] }));
  assert.ok(isDemoActive({ ...base, sessions: ['ses_demo', 'ses_real_interview'] }));
});
