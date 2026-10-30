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

  setSession: (sessionId) => set({ sessionId }),
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
   * 전사와 달리 잘라내지 않는다 — 흘러가는 기록이 아니라 면접관이 골라 쓰는 목록이다.
   */
  addSuggestion: (suggestion) =>
    set((s) =>
      s.suggestions.some((x) => x.id === suggestion.id)
        ? {}
        : { suggestions: [...s.suggestions, suggestion] },
    ),

  /**
   * 조회 API 결과를 지금 목록과 합친다 (입장 · 재연결).
   *
   * 순서는 서버가 받은 순서를 따른다. 끊긴 사이에 온 것이 여기서 되살아나므로,
   * 서버 목록이 기준이고 아직 서버 응답에 없는(방금 패킷으로 받은) 것만 뒤에 붙인다.
   * 고정은 서버가 모르는 값이라 이쪽에서 지켜 준다.
   */
  mergeSuggestions: (list) =>
    set((s) => {
      const pinned = new Set(s.suggestions.filter((x) => x.pinned).map((x) => x.id));
      const fromServer = new Set(list.map((x) => x.id));
      return {
        suggestions: [
          ...list.map((x) => (pinned.has(x.id) ? { ...x, pinned: true } : x)),
          ...s.suggestions.filter((x) => !fromServer.has(x.id)),
        ],
      };
    }),

  /** 면접관이 「이걸 묻겠다」고 눌렀다 · 눌렀던 것을 풀었다 */
  toggleSuggestionPin: (id) =>
    set((s) => ({
      suggestions: s.suggestions.map((x) => (x.id === id ? { ...x, pinned: !x.pinned } : x)),
    })),

  reset: () =>
    set({
      sessionId: null,
      connection: 'disconnected',
      remoteJoined: false,
      speakingNow: null,
      utterances: [],
      transcriptDegraded: false,
      suggestions: [],
    }),
}));
