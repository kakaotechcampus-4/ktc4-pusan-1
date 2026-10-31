import type { Coverage, Finding, ReviewStatus } from './interview';

export interface ReportStatement {
  text: string;
  findingId: string;
  findingType: Finding['type'];
  source: string | null;
  quote: string | null;
  transcript: string | null;
  atSec: number | null;
}

export interface ReportCompetency {
  name: string;
  required: boolean;
  state: Coverage['state'];
  confirmed: ReportStatement[];
  unconfirmed: ReportStatement[];
  nextQuestions: string[];
}

export interface ReportDocument {
  status: 'READY' | 'FAILED';
  interviewId: string;
  sessionId: string;
  generatedAt: string | null;
  reviewStatus: ReviewStatus;
  candidate: { name: string | null; role: string };
  interviewer: { nickname: string };
  interviewedAt: string | null;
  memo: string;
  overview: string;
  competencies: ReportCompetency[];
  failureReason: 'NO_EVIDENCE' | null;
}

/** NOT_CREATED는 서버의 REPORT_NOT_FOUND를 화면에서 표현하는 값이다. */
export type ReportResponse =
  { status: 'NOT_CREATED' } | { status: 'PROCESSING'; etaSec: number | null } | ReportDocument;
