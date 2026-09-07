/**
 * 화면 로컬 상태.
 *
 * 서버 데이터(컨텍스트·리뷰·목록)는 TanStack Query,
 * 통화 세션(연결·트랙)은 LiveKit Room이 소유한다.
 * 여기에는 화면이 그리는 것만 둔다.
 */

import { ConnectionState } from 'livekit-client';
import { create } from 'zustand';
import type { Speaker, StreamEvent, Suggestion, Utterance } from '../types/interview';

interface InterviewState {
  sessionId: string | null;
  connection: ConnectionState;

  /** 지원자 참가 여부 — 미참가 시 대기 화면 */
  candidateJoined: boolean;
  /** 현재 말하는 화자. null이면 무음 */
  speakingNow: Speaker | null;

  utterances: Utterance[];
  suggestions: Suggestion[];

  /** 전사가 끊긴 상태. 통화는 유지된다 */
  transcriptDegraded: boolean;

  transcriptOpen: boolean;
  suggestionsOpen: boolean;

  setSession: (id: string) => void;
  setConnection: (s: ConnectionState) => void;
  setCandidateJoined: (v: boolean) => void;
  setSpeaking: (s: Speaker | null) => void;
  applyStreamEvent: (e: StreamEvent) => void;
  markAsked: (id: string) => void;
  unmarkAsked: (id: string) => void;
  toggleTranscript: () => void;
  toggleSuggestions: () => void;
  reset: () => void;
}

export const useInterviewStore = create<InterviewState>((set) => ({
  sessionId: null,
  connection: ConnectionState.Disconnected,
  candidateJoined: false,
  speakingNow: null,
  utterances: [],
  suggestions: [],
  transcriptDegraded: false,
  transcriptOpen: true,
  suggestionsOpen: true,

  setSession: (sessionId) => set({ sessionId }),
  setConnection: (connection) => set({ connection }),
  setCandidateJoined: (candidateJoined) => set({ candidateJoined }),
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
          // 화면에는 최근 6줄만 남긴다.
          return { utterances: next.slice(-6) };
        }

        // 추천 질문은 지원자 발화 종료 후에만 도착한다.
        // 면접관 발화에는 서버가 생성하지 않는다.
        //
        // 3개까지만 남긴다. 4개면 패널이 세로로 786px 까지 자라 768px 화면을
        // 넘어가고, 마지막 질문의 버튼이 잘려 눌리지 않는다.
        case 'suggestion.created':
          return {
            suggestions: [
              ...s.suggestions,
              { id: e.id, text: e.text, reason: e.reason, atSec: e.at, asked: false },
            ].slice(-3),
          };

        case 'stream.degraded':
          return { transcriptDegraded: true, speakingNow: null };

        default:
          return {};
      }
    }),

  markAsked: (id) =>
    set((s) => ({
      suggestions: s.suggestions.map((q) => (q.id === id ? { ...q, asked: true } : q)),
    })),

  unmarkAsked: (id) =>
    set((s) => ({
      suggestions: s.suggestions.map((q) => (q.id === id ? { ...q, asked: false } : q)),
    })),

  toggleTranscript: () => set((s) => ({ transcriptOpen: !s.transcriptOpen })),
  toggleSuggestions: () => set((s) => ({ suggestionsOpen: !s.suggestionsOpen })),

  reset: () =>
    set({
      sessionId: null,
      connection: ConnectionState.Disconnected,
      candidateJoined: false,
      speakingNow: null,
      utterances: [],
      suggestions: [],
      transcriptDegraded: false,
    }),
}));
