import { ApiError, request } from './client';
import type { ReportResponse } from '../types/report';

export async function getReport(interviewId: string): Promise<ReportResponse> {
  try {
    return await request<ReportResponse>(`/api/v1/interviews/${interviewId}/report`);
  } catch (error) {
    if (error instanceof ApiError && error.code === 'REPORT_NOT_FOUND') {
      return { status: 'NOT_CREATED' };
    }
    throw error;
  }
}

export const createReport = (interviewId: string) =>
  request<{ status: 'PROCESSING'; etaSec: number | null }>(
    `/api/v1/interviews/${interviewId}/report`,
    { method: 'POST' },
  );
