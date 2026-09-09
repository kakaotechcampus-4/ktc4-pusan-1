/**
 * 화면 로컬 상태.
 *
 * 서버 데이터(컨텍스트·리뷰·목록)는 TanStack Query,
 * 통화 세션(연결·트랙)은 LiveKit Room이 소유한다.
 * 여기에는 화면이 그리는 것만 둔다.
 */

import { ConnectionState } from 'livekit-client';
import { create } from 'zustand';
import type { Speaker, StreamEvent, Utterance } from '../types/interview';

interface InterviewState {
  sessionId: string | null;
  connection: ConnectionState;

  /** 상대 참가 여부 — 미참가 시 대기 화면. 면접관에겐 지원자, 지원자에겐 면접관이다 */
  remoteJoined: boolean;
  /** 현재 말하는 화자. null이면 무음 */
  speakingNow: Speaker | null;

  utterances: Utterance[];

  /** 전사가 끊긴 상태. 통화는 유지된다 */
  transcriptDegraded: boolean;

  transcriptOpen: boolean;

  setSession: (id: string) => void;
  setConnection: (s: ConnectionState) => void;
  setRemoteJoined: (v: boolean) => void;
  setSpeaking: (s: Speaker | null) => void;
  applyStreamEvent: (e: StreamEvent) => void;
  toggleTranscript: () => void;
  reset: () => void;
}

export const useInterviewStore = create<InterviewState>((set) => ({
  sessionId: null,
  connection: ConnectionState.Disconnected,
  remoteJoined: false,
  speakingNow: null,
  utterances: [],
  transcriptDegraded: false,
  transcriptOpen: true,

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
          // 화면에는 최근 6줄만 남긴다.
          return { utterances: next.slice(-6) };
        }

        case 'stream.degraded':
          return { transcriptDegraded: true, speakingNow: null };

        default:
          return {};
      }
    }),

  toggleTranscript: () => set((s) => ({ transcriptOpen: !s.transcriptOpen })),

  reset: () =>
    set({
      sessionId: null,
      connection: ConnectionState.Disconnected,
      remoteJoined: false,
      speakingNow: null,
      utterances: [],
      transcriptDegraded: false,
    }),
}));
