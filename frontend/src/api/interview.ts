import type { EndSessionResponse, StartInterviewResponse } from '../types/interview';
import { request } from './client';

/** 방 생성 + 토큰 발급. 방 생성은 서버가 담당한다. */
export const startInterview = (interviewId: string) =>
  request<StartInterviewResponse>(`/interviews/${interviewId}/start`, { method: 'POST' });

export const endSession = (sessionId: string) =>
  request<EndSessionResponse>(`/sessions/${sessionId}/end`, { method: 'POST' });

export const askSuggestion = (sessionId: string, suggestionId: string) =>
  request<void>(`/sessions/${sessionId}/suggestions/${suggestionId}/ask`, { method: 'POST' });
