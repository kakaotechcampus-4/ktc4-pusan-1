/**
 * 화면 로컬 상태.
 *
 * 서버 데이터(컨텍스트·리뷰·목록)는 TanStack Query,
 * 통화 세션(연결·트랙)은 LiveKit Room이 소유한다.
 * 여기에는 화면이 그리는 것만 둔다.
 */

import { create } from 'zustand';
import type {
  RoomConnectionState,
  Speaker,
  StreamEvent,
  Suggestion,
  Utterance,
} from '../types/interview';
import {
  raiseFloor,
  readMarks,
  refillFloor,
  canRestore,
  trimSuggestions,
  visibleSuggestions,
  writeMarks,
  type SuggestionLimit,
  type SuggestionQueue,
} from '../lib/suggestionQueue.ts';

interface InterviewState {
  sessionId: string | null;
  connection: RoomConnectionState;

  /** 상대 참가 여부 — 미참가 시 대기 화면. 면접관에겐 지원자, 지원자에겐 면접관이다 */
  remoteJoined: boolean;
  /** 현재 말하는 화자. null이면 무음 */
  speakingNow: Speaker | null;

  utterances: Utterance[];

  /** 전사가 끊긴 상태. 통화는 유지된다 */
  transcriptDegraded: boolean;

  transcriptOpen: boolean;

  /** AI 꼬리질문. 면접관에게만 온다 (#212) */
  suggestions: Suggestion[];
  questionsExpanded: boolean;
  toggleQuestionsExpanded: () => void;
  /** 고정되지 않은 질문을 몇 개까지 보여줄지. 면접관이 6 · 10 중에 고른다 */
  suggestionLimit: SuggestionLimit;
  setSuggestionLimit: (limit: SuggestionLimit) => void;
  /** 지운 질문 id. 그 칸은 다음 질문이 올 때까지 비어 있다 */
  hiddenSuggestionIds: string[];
  lastHiddenSuggestionId: string | null;
  pinnedSuggestionIds: string[];
  dismissSuggestion: (id: string) => void;
  undoDismissSuggestion: () => void;
  /** 일시정지 중에 화면에 붙잡아 둔 질문 id. null 이면 큐가 흐른다 */
  frozenSuggestionIds: string[] | null;
  toggleSuggestionsPaused: () => void;
  /** 큐에 남아 있는 가장 오래된 도착 순번. 밀려난 질문은 이보다 작아 다시 나오지 않는다 */
  suggestionFloor: number;
  /** 받은 적 있는 질문의 도착 순번. 잘라낸 질문이 재조회로 되살아나지 않게 한다 */
  suggestionSeq: Record<string, number>;
  /** 새로고침 전 큐의 시작 질문 id. 조회로 그 질문이 다시 오면 floor 를 거기로 맞춘다 */
  restoredFloorId: string | null;

  setSession: (id: string) => void;
  setConnection: (s: RoomConnectionState) => void;
  setRemoteJoined: (v: boolean) => void;
  setSpeaking: (s: Speaker | null) => void;
  applyStreamEvent: (e: StreamEvent) => void;
  toggleTranscript: () => void;
  addSuggestion: (s: Suggestion) => void;
  mergeSuggestions: (list: Suggestion[]) => void;
  toggleSuggestionPin: (id: string) => void;
  reset: () => void;
}

export const useInterviewStore = create<InterviewState>((set) => ({
  sessionId: null,
  connection: 'disconnected',
  remoteJoined: false,
  speakingNow: null,
  utterances: [],
  transcriptDegraded: false,
  transcriptOpen: true,
  suggestions: [],
  questionsExpanded: false,
  toggleQuestionsExpanded: () => set((s) => ({ questionsExpanded: !s.questionsExpanded })),

  suggestionLimit: 6,
  // 늘리면 보관 중인 질문으로 바로 채우고, 줄이면 오래된 것부터 뺀다.
  setSuggestionLimit: (suggestionLimit) =>
    set((s) =>
      settle(
        s,
        { suggestionLimit },
        suggestionLimit > s.suggestionLimit ? refillFloor : raiseFloor,
      ),
    ),
  hiddenSuggestionIds: [],
  lastHiddenSuggestionId: null,
  pinnedSuggestionIds: [],
  frozenSuggestionIds: null,
  suggestionFloor: 0,
  suggestionSeq: {},
  restoredFloorId: null,

  // 이 탭에서 지우고 고정해 둔 것을 되살린다. 질문은 뒤이어 조회 · 패킷으로 채워진다.
  setSession: (sessionId) =>
    set(() => {
      const marks = readMarks(sessionId);
      return {
        sessionId,
        hiddenSuggestionIds: marks.hidden,
        pinnedSuggestionIds: marks.pinned,
        restoredFloorId: marks.floor,
      };
    }),
  setConnection: (connection) => set({ connection }),
  setRemoteJoined: (remoteJoined) => set({ remoteJoined }),
  setSpeaking: (speakingNow) => set({ speakingNow }),

  applyStreamEvent: (e) =>
    set((s) => {
      switch (e.type) {
        case 'speech.start':
          return { speakingNow: e.speaker };

        case 'speech.end':
          return { speakingNow: null };

        // 같은 utteranceId 조각을 이어 붙인다.
        case 'transcript.delta': {
          const i = s.utterances.findIndex((u) => u.id === e.utteranceId);
          const next = [...s.utterances];
          if (i >= 0) {
            next[i] = { ...next[i], text: next[i].text + e.text, final: e.final };
          } else {
            next.push({
              id: e.utteranceId,
              speaker: e.speaker,
              text: e.text,
              atSec: e.at,
              final: e.final,
            });
          }
          // 큰 화면에서도 여러 발화를 읽을 수 있게 하되 화면 캐시는 한정한다.
          return { utterances: next.slice(-50), transcriptDegraded: false };
        }

        case 'stream.degraded':
          return { transcriptDegraded: true, speakingNow: null };

        default:
          return {};
      }
    }),

  toggleTranscript: () => set((s) => ({ transcriptOpen: !s.transcriptOpen })),

  /**
   * 실시간으로 받은 꼬리질문 하나를 뒤에 붙인다.
   *
   * 같은 id 가 다시 와도 먼저 온 것을 남긴다. 덮으면 면접관이 눌러 둔 고정이 풀려,
   * 묻기 직전에 표시가 사라진다. BE 도 재시도를 받으면 처음 것을 남긴다.
   *
   * 큐라서 고정 · 일시정지로 붙잡지 않은 오래된 질문은 잘라낸다.
   */
  addSuggestion: (suggestion) =>
    set((s) =>
      suggestion.id in s.suggestionSeq
        ? {}
        : settle(s, {
            suggestions: [...s.suggestions, markPinned(suggestion, s.pinnedSuggestionIds)],
            suggestionSeq: { ...s.suggestionSeq, [suggestion.id]: nextSeq(s.suggestionSeq) },
          }),
    ),

  /**
   * 조회 API 결과를 지금 목록과 합친다 (입장 · 재연결).
   *
   * 끊긴 사이에 온 것은 서버가 받은 순서대로 뒤에 붙인다. 이미 받은 적 있는 질문은
   * 건너뛴다 — 큐에서 밀려나 잘라낸 질문이 재조회로 되살아나면 안 된다.
   * 고정은 서버가 모르는 값이라 이쪽에서 지켜 준다.
   */
  mergeSuggestions: (list) =>
    set((s) => {
      const seq = { ...s.suggestionSeq };
      const fresh: Suggestion[] = [];
      for (const x of list) {
        if (x.id in seq) continue;
        seq[x.id] = nextSeq(seq);
        fresh.push(markPinned(x, s.pinnedSuggestionIds));
      }
      return settle(s, { suggestions: [...s.suggestions, ...fresh], suggestionSeq: seq });
    }),

  // 지운 질문은 고정도 함께 푼다. 고정된 채 숨으면 잘리지 않고 영영 남는다.
  dismissSuggestion: (id) =>
    set((s) => {
      const next = {
        hiddenSuggestionIds: [...new Set([...s.hiddenSuggestionIds, id])],
        lastHiddenSuggestionId: id,
        pinnedSuggestionIds: s.pinnedSuggestionIds.filter((x) => x !== id),
        suggestions: s.suggestions.map((x) => (x.id === id ? { ...x, pinned: false } : x)),
      };
      return settle(s, next);
    }),
  undoDismissSuggestion: () =>
    set((s) => {
      const hidden = s.hiddenSuggestionIds.filter((id) => id !== s.lastHiddenSuggestionId);
      return settle(s, { hiddenSuggestionIds: hidden, lastHiddenSuggestionId: null });
    }),

  toggleSuggestionsPaused: () =>
    set((s) =>
      s.frozenSuggestionIds
        ? settle(s, { frozenSuggestionIds: null })
        : { frozenSuggestionIds: visibleSuggestions(queueOf(s)).map((x) => x.id) },
    ),

  /** 면접관이 「이걸 묻겠다」고 눌렀다 · 눌렀던 것을 풀었다 */
  toggleSuggestionPin: (id) =>
    set((s) => {
      const pinnedSuggestionIds = s.pinnedSuggestionIds.includes(id)
        ? s.pinnedSuggestionIds.filter((x) => x !== id)
        : [...s.pinnedSuggestionIds, id];
      return settle(s, {
        pinnedSuggestionIds,
        suggestions: s.suggestions.map((x) =>
          x.id === id ? { ...x, pinned: pinnedSuggestionIds.includes(id) } : x,
        ),
      });
    }),

  reset: () =>
    set({
      sessionId: null,
      connection: 'disconnected',
      remoteJoined: false,
      speakingNow: null,
      utterances: [],
      transcriptDegraded: false,
      suggestions: [],
      questionsExpanded: false,
      hiddenSuggestionIds: [],
      lastHiddenSuggestionId: null,
      pinnedSuggestionIds: [],
      frozenSuggestionIds: null,
      suggestionFloor: 0,
      suggestionSeq: {},
      restoredFloorId: null,
    }),
}));

const markPinned = (s: Suggestion, pinned: readonly string[]): Suggestion =>
  pinned.includes(s.id) ? { ...s, pinned: true } : s;

const nextSeq = (seq: Record<string, number>) => Object.keys(seq).length;

export const queueOf = (s: InterviewState): SuggestionQueue => ({
  suggestions: s.suggestions,
  hidden: s.hiddenSuggestionIds,
  limit: s.suggestionLimit,
  floor: s.suggestionFloor,
  seq: s.suggestionSeq,
  frozen: s.frozenSuggestionIds,
});

/**
 * 바뀐 상태에 큐 규칙을 적용한다 — 넘친 만큼 floor 를 옮기고 보관 범위 밖은 잘라낸다.
 * 지우기 · 고정 · floor 는 이 탭에 남겨 새로고침 뒤에도 같은 큐를 보이게 한다.
 */
function settle(
  s: InterviewState,
  patch: Partial<InterviewState>,
  floorOf: (q: SuggestionQueue) => number = raiseFloor,
): Partial<InterviewState> {
  const next = { ...s, ...patch };
  const q = queueOf(next);
  const restored = next.restoredFloorId === null ? undefined : q.seq[next.restoredFloorId];
  const floor = Math.max(floorOf(q), restored ?? -Infinity);
  writeMarks(next.sessionId, {
    hidden: next.hiddenSuggestionIds,
    pinned: next.pinnedSuggestionIds,
    floor: Object.keys(q.seq).find((id) => q.seq[id] === floor) ?? null,
  });
  const suggestions = trimSuggestions({ ...q, floor });
  const last = next.lastHiddenSuggestionId;
  const stale = last !== null && !canRestore({ ...q, floor, suggestions }, last);
  return {
    ...patch,
    suggestionFloor: floor,
    suggestions,
    ...(stale ? { lastHiddenSuggestionId: null } : {}),
    ...(restored === undefined ? {} : { restoredFloorId: null }),
  };
}
