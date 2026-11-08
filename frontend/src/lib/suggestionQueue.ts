import type { Suggestion } from '../types/interview';

/** 면접관이 고를 수 있는 표시 개수. 큰 값이 곧 화면이 보관하는 최대치다 */
export const SUGGESTION_LIMITS = [6, 10] as const;
export type SuggestionLimit = (typeof SUGGESTION_LIMITS)[number];
const KEEP = Math.max(...SUGGESTION_LIMITS);

/**
 * 꼬리질문 큐의 상태.
 *
 * 질문마다 도착 순번(`seq`)을 매기고, 순번이 `floor` 이상인 질문만 큐에 있다고 본다.
 * 질문이 창 밖으로 밀리면 `floor` 가 올라가므로, 지운 칸을 채우려고 이미 지나간 질문이
 * 되살아나는 일이 없다. 표시 개수를 늘릴 때만 보관 중인 질문으로 `floor` 를 내린다.
 */
export interface SuggestionQueue {
  suggestions: readonly Suggestion[];
  hidden: readonly string[];
  limit: SuggestionLimit;
  floor: number;
  seq: Readonly<Record<string, number>>;
  /** 일시정지 중에 붙잡아 둔 목록. null 이면 큐가 흐른다 */
  frozen: readonly string[] | null;
}

const queued = (q: SuggestionQueue, floor: number) => {
  const gone = new Set(q.hidden);
  return q.suggestions.filter((s) => !s.pinned && !gone.has(s.id) && (q.seq[s.id] ?? 0) >= floor);
};

/**
 * 화면에 올릴 꼬리질문. 고정한 질문은 큐 밖에 두고 위에 올린다.
 * 나머지는 큐의 최신 `limit` 개를 최신순으로 둔다. 일시정지 중에는 붙잡아 둔 목록만 둔다.
 */
export function visibleSuggestions(q: SuggestionQueue): Suggestion[] {
  const gone = new Set(q.hidden);
  if (q.frozen) {
    const byId = new Map(q.suggestions.map((s) => [s.id, s]));
    return q.frozen.flatMap((id) => {
      const s = byId.get(id);
      return s && !gone.has(id) ? [s] : [];
    });
  }
  const pinned = q.suggestions.filter((s) => s.pinned && !gone.has(s.id)).reverse();
  return [...pinned, ...queued(q, q.floor).slice(-q.limit).reverse()];
}

/** 창을 넘친 만큼 `floor` 를 올린다. 지운 칸은 비워 둔 채로 둔다 */
export function raiseFloor(q: SuggestionQueue): number {
  const list = queued(q, q.floor);
  return list.length > q.limit ? q.seq[list[list.length - q.limit].id] : q.floor;
}

/** 표시 개수를 늘렸을 때 보관 중인 질문으로 창을 채운다 */
export function refillFloor(q: SuggestionQueue): number {
  const list = queued(q, -Infinity);
  const head = list[Math.max(0, list.length - q.limit)];
  return head ? Math.min(q.floor, q.seq[head.id]) : q.floor;
}

/**
 * 화면이 보관할 질문만 남긴다. 고정한 질문, 붙잡아 둔 질문, 지우지 않은 최신 `KEEP` 개와
 * 그보다 새로 지운 질문이다. 면접이 길어져도 목록이 끝없이 늘지 않게 한다.
 */
export function trimSuggestions(q: SuggestionQueue): Suggestion[] {
  const list = queued(q, -Infinity);
  const oldest = list.length > KEEP ? q.seq[list[list.length - KEEP].id] : -Infinity;
  const held = new Set(q.frozen ?? []);
  return q.suggestions.filter((s) => s.pinned || held.has(s.id) || (q.seq[s.id] ?? 0) >= oldest);
}

export interface SuggestionMarks {
  hidden: string[];
  pinned: string[];
}

const marksKey = (sessionId: string) => `irya.suggestions.${sessionId}`;
const strings = (value: unknown) =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];

/**
 * 지우기·고정은 서버에 적는 API 가 없어 이 탭의 sessionStorage 에 둔다.
 * 새로고침·재입장 때 조회 API 가 질문을 다시 채워도 지운 질문이 되살아나지 않는다.
 * 저장소를 못 쓰는 환경(사생활 보호 모드 등)에서는 조용히 메모리로만 동작한다.
 */
export function readMarks(sessionId: string): SuggestionMarks {
  try {
    const saved = JSON.parse(globalThis.sessionStorage?.getItem(marksKey(sessionId)) ?? 'null');
    return { hidden: strings(saved?.hidden), pinned: strings(saved?.pinned) };
  } catch {
    return { hidden: [], pinned: [] };
  }
}

export function writeMarks(sessionId: string | null, marks: SuggestionMarks) {
  if (!sessionId) return;
  try {
    globalThis.sessionStorage?.setItem(marksKey(sessionId), JSON.stringify(marks));
  } catch {
    // 저장 공간이 없어도 화면 동작은 그대로 둔다.
  }
}
