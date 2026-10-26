/**
 * 면접 도메인 타입 — BE API 명세 기준.
 *
 * 응답 필드는 각 문서의 Response 표를 그대로 옮긴 것이다.
 * 명세에 없어서 FE 가 정한 부분은 ⚠️ 로 표시했다.
 */

/**
 * 전사 화자.
 *
 * `Role`(입장 권한)과 값은 같지만 축이 다르다 — 권한은 "무엇을 할 수 있는가",
 * 화자는 "누가 말했는가"다. AI·BE 가 대문자를 쓰므로 표기를 맞춰 두었다.
 */
export type Speaker = 'INTERVIEWER' | 'CANDIDATE';

/**
 * 입장 권한.
 *
 * 현재는 클라이언트가 join 요청에 실어 보낸다 (인증 도입 전 임시 구조).
 * 서버가 판단하도록 바뀌면 joinSession 호출부 한 곳만 고치면 된다.
 */
export type Role = 'INTERVIEWER' | 'CANDIDATE';

/** Session 진행 상태 */
export type SessionStatus = 'WAITING' | 'INTERVIEWING' | 'ENDED';

/** LiveKit 연결 상태를 화면 표시용 문자열로만 보관한다. */
export type RoomConnectionState =
  'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'signalReconnecting';

/* ---------------------------------------------------------------- *
 * 면접
 * ---------------------------------------------------------------- */

/** POST /api/v1/interviews · GET /api/v1/interviews/{interviewId} */
export interface Interview {
  interviewId: string;
  interviewerId: string;
  /** 면접관 화면에 표시할 지원자 이름 */
  candidateName: string | null;
  createdAt: string;
}

/**
 * 면접관의 검토 진행 상태.
 *
 * 한글 표시는 FE 가 한다 — 서버는 값만 준다 (#137 1-3).
 */
export type ReviewStatus = 'PENDING' | 'IN_REVIEW' | 'CONFIRMED';

/**
 * 목록 한 줄의 검토 항목 집계.
 *
 * 상세 화면과 같은 계산에서 나오므로 두 화면의 숫자가 어긋나지 않는다.
 */
export interface ReviewCounts {
  /** 확인된 항목 수 / 전체 */
  coverageConfirmed: number;
  coverageTotal: number;
  /** AI 가 짚은 항목 전체 */
  findings: number;
  /** 아직 채택도 반려도 안 한 항목 */
  needsReview: number;
  adopted: number;
}

/**
 * GET /api/v1/interviews 의 한 줄 (#137 1-1).
 *
 * 기준은 그 면접의 **마지막으로 끝난 세션**이다. 끝난 세션이 없으면 거기서 오는 값
 * (`interviewedAt` · `durationSec` · `summaryStatus`)이 모두 null 이다 — 만들어 놓고
 * 아직 안 본 면접이 그렇다.
 */
export interface InterviewListItem {
  interviewId: string;
  candidateName: string | null;
  /** 내 컨텍스트의 직무. 아직 안 정했으면 빈 문자열 */
  role: string;
  /** 면접관은 늘 나다. 서버가 토큰의 사용자를 넣어 준다 */
  interviewer: { nickname: string };
  /** 「면접 시작」 시각. 비어 있으면 첫 입장 시각 */
  interviewedAt: string | null;
  durationSec: number | null;
  reviewStatus: ReviewStatus;
  /** 한도를 넘긴 PROCESSING 은 FAILED 로 온다 */
  summaryStatus: SummaryStatus | null;
  /** 요약이 READY 가 아니면 null 이다 — 셀 수 있는 것이 아직 없다 */
  counts: ReviewCounts | null;
}

/** GET /api/v1/interviews */
export interface InterviewListResponse {
  items: InterviewListItem[];
}

/** POST /api/v1/interviews/{interviewId}/sessions */
export interface CreateSessionResponse {
  sessionId: string;
  interviewId: string;
  candidateName: string | null;
  status: SessionStatus;
  /** 지원자에게 전달할 면접 링크 */
  inviteUrl: string;
  createdAt: string;
}

/** POST /api/v1/sessions/{sessionId}/start */
export interface StartSessionResponse {
  sessionId: string;
  status: SessionStatus;
  startedAt: string;
}

/** GET /api/v1/sessions/{sessionId} — 새로고침·재접속 시 상태 복구용 */
export interface SessionState {
  sessionId: string;
  interviewId: string;
  candidateName: string | null;
  status: SessionStatus;
  startedAt: string | null;
  endedAt: string | null;
}

/**
 * 면접 요약 (이슈 #6).
 *
 * 요약은 면접이 끝난 뒤 HTTP로 조회한다. 상태와 본문은 공개 BE 명세를 따른다.
 *
 *   GET /api/v1/sessions/{sessionId}/summary
 *
 * LLM 요약은 시간이 걸리므로 생성 중 상태가 필요하다.
 */
export type SummaryStatus = 'PROCESSING' | 'READY' | 'FAILED';

export interface InterviewSummary {
  sessionId: string;
  status: SummaryStatus;
  /** status 가 READY 일 때만 채워진다 */
  content: {
    /** 면접 전체를 한 문단으로 */
    overview: string;
    /** 지원자 답변에서 뽑은 핵심 */
    keyPoints: string[];
  } | null;
  durationSec: number;
}

/** POST /api/v1/sessions/{sessionId}/end */
export interface EndSessionResponse {
  sessionId: string;
  status: SessionStatus;
  endedAt: string;
}

/* ---------------------------------------------------------------- *
 * 기업 컨텍스트 (S1)
 *
 * 공개 BE 명세의 조회·저장·문서 업로드 계약이다.
 * ---------------------------------------------------------------- */

/**
 * 문서 형식.
 *
 * 새로 올릴 수 있는 것은 PDF 뿐이지만(#149), 그 전에 올라온 DOCX 가 조회 응답에
 * 그대로 남아 있어서 읽는 쪽은 둘 다 받는다.
 */
export type DocKind = 'pdf' | 'docx';

/**
 * 기업 컨텍스트 문서가 들어가는 칸.
 *
 * AI 가 JD 와 사내 문서를 다르게 쓴다. 이력서에는 칸이 없어서 null 로 온다.
 */
export type DocCategory = 'jd' | 'internal';

/**
 * 문서 상태.
 *
 * uploading 은 클라이언트에만 있는 상태다 — 서버는 업로드가 끝난 뒤에야 문서를 안다.
 * 올라온 직후는 parsing 이고, 서버가 본문을 뽑으면 ready, 못 뽑으면 failed 가 된다.
 */
export type DocStatus = 'uploading' | 'parsing' | 'ready' | 'failed';

export interface ContextDoc {
  id: string;
  name: string;
  kind: DocKind;
  sizeBytes: number;
  status: DocStatus;
  /** 어느 칸에 들어가는지. 이력서는 null 이고, 업로드 중인 임시 문서에는 없다 */
  category?: DocCategory | null;
  /** 업로드 진행률 0~1. uploading 일 때만 있다 */
  progress?: number;
}

/** GET /api/v1/contexts/current */
export interface CompanyContext {
  id: string;
  company: string;
  team: string;
  role: string;
  /** AI 면접관이 참고할 추가 인재상. 명세상 항상 온다 (빈 문자열일 수 있다) */
  talentProfile: string;
  docs: ContextDoc[];
}

/** 업로드 거부 사유. 서버에 보내기 전에 FE 가 먼저 거른다. */
export type UploadRejection = 'unsupported-type' | 'too-large' | 'empty-file';

/* ---------------------------------------------------------------- *
 * 면접 기록 (S3)
 *
 * 서버가 주는 모양 그대로다 (#137 1-2 · #163). 녹화는 이 응답에 실리지 않고
 * `sessionId` 로 녹화 API 를 따로 부른다 — 서명 URL 이 10분 만에 만료돼서,
 * 상세와 같이 캐시해 두면 다시 열 때 이미 죽은 주소가 된다.
 * ---------------------------------------------------------------- */

/** 질문 하나가 시작된 시점과 그 문답 */
export interface Moment {
  id: string;
  /** 전사 원점(t=0) 기준 경과 초. 녹화 재생 위치와는 `offsetMs` 만큼 다르다 */
  atSec: number;
  /** 타임라인 아래 짧은 라벨 */
  label: string;
  /** 면접관 발화 원문 */
  question: string;
  /** 답변 요약 (한두 줄) */
  answer: string;
  /** 근거 시각이 이 문답 구간에 드는 검토 항목의 역량 */
  competencies: string[];
  bookmarked: boolean;
}

/** 역량 하나가 면접에서 얼마나 확인됐는가 */
export interface Coverage {
  name: string;
  state: 'CONFIRMED' | 'PARTIAL' | 'MISSING';
}

/** 검토 항목 하나 — AI 가 근거와 함께 낸 관찰. 판정이 아니다 */
export interface Finding {
  id: string;
  type:
    'COMPETENCY_EVIDENCE' | 'CLAIM_VERIFIED' | 'CLAIM_CONTRADICTED' | 'CLAIM_UNVERIFIED' | 'GAP';
  state: 'PROPOSED' | 'ADOPTED' | 'REJECTED';
  rationale: string;
  competency: string | null;
  /** 지원서의 문장 */
  quote: string | null;
  /** 근거가 된 면접 발화 */
  transcript: string | null;
  /** 「지원서 · 단락」 또는 「면접 답변」 */
  source: string | null;
  atSec: number | null;
}

/** 요약 본문. `summaryStatus` 가 READY 일 때만 찬다 */
export interface SummaryContent {
  /** 면접 전체를 한 문단으로 */
  overview: string;
  /** 지원자 답변에서 뽑은 핵심 */
  keyPoints: string[];
}

export interface Review {
  interviewId: string;
  /** 기준 세션. 녹화는 이 id 로 `GET /sessions/{sessionId}/recording` */
  sessionId: string;
  candidate: { name: string | null; role: string };
  interviewer: { nickname: string };
  interviewedAt: string | null;
  durationSec: number | null;
  reviewStatus: ReviewStatus;
  reviewedAt: string | null;
  memo: string;
  summaryStatus: SummaryStatus;
  /** 요약이 READY 가 아니면 null */
  summary: SummaryContent | null;
  coverage: Coverage[];
  moments: Moment[];
  findings: Finding[];
}

/**
 * GET /api/v1/interviews/{interviewId}/review
 *
 * 녹화 변환과 AI 평가에 시간이 걸리므로, 준비 전에는 202 와 PROCESSING 을 돌려준다.
 */
export type ReviewResponse =
  { status: 'PROCESSING'; etaSec?: number } | ({ status: 'READY' } & Review);

/** PATCH /api/v1/interviews/{interviewId} — 보낸 것만 바뀐다 (#137 1-3) */
export interface ReviewUpdate {
  reviewStatus?: ReviewStatus;
  /** 최대 4000자. 비우려면 빈 문자열 */
  memo?: string;
}

export interface ReviewUpdateResponse {
  reviewStatus: ReviewStatus;
  /** CONFIRMED 가 된 시각. 다른 상태로 돌아가면 null */
  reviewedAt: string | null;
  memo: string;
}

/**
 * PUT /api/v1/interviews/{interviewId}/review/marks/{itemId} (#137 1-4).
 *
 * 검토 항목은 `state` 만, 문답은 `bookmarked` 만 받는다 — 반대로 보내면 422 다.
 */
export type MarkUpdate = { state: Finding['state'] } | { bookmarked: boolean };

export interface MarkResponse {
  itemId: string;
  state: Finding['state'];
  bookmarked: boolean;
}

/**
 * GET /api/v1/sessions/{sessionId}/recording
 *
 * 합친 파일 하나의 서명 URL 이다 (#112). 10분 뒤 만료된다.
 */
export interface Recording {
  url: string;
  durationSec: number;
  /**
   * 녹화의 0초가 전사 원점(t=0)보다 얼마나 뒤인가.
   * 전사 시각 t(ms) 의 장면은 녹화의 `t − offsetMs` 에 있다.
   */
  offsetMs: number;
  expiresAt: string;
}

/**
 * 녹화 조회 결과.
 *
 * 합치는 중이면 202 PROCESSING 이고, 녹화가 없거나 합치지 못했으면 404 다.
 * 404 는 오류가 아니다 — 녹화 없이 전사로 검토하는 정상 경로다.
 */
export type RecordingResponse =
  { status: 'PROCESSING' } | ({ status: 'READY' } & Recording) | { status: 'NONE' };

/* ---------------------------------------------------------------- *
 * 진입
 * ---------------------------------------------------------------- */

/** POST /api/v1/sessions/{sessionId}/join */
export interface JoinSessionResponse {
  sessionId: string;
  /** 면접관 화면에 표시할 지원자 이름 */
  candidateName: string | null;
  /** LiveKit 서버 접속 URL */
  livekitUrl: string;
  /** LiveKit Room 입장용 Access Token */
  token: string;
  /** 매핑된 LiveKit Room 이름 */
  roomName: string;
}

/**
 * join 실패 사유.
 *
 * 서버가 `error.code` 로 사유를 구분해 주므로 409 를 두 갈래로 나눈다.
 * 매핑은 api/interview.ts 의 FAILURE_BY_CODE 에 있다.
 */
export type JoinFailure =
  /** 존재하지 않는 세션 */
  | 'not-found'
  /** 로그인은 했지만 이 면접의 주인이 아니다 — 다시 시도해도 같다 (#150) */
  | 'not-allowed'
  /**
   * 면접관으로 들어가려는데 토큰이 없거나 만료됐다 (401).
   *
   * 이때 client.ts 가 토큰을 이미 지웠으므로 다시 눌러도 영원히 같다 — 「잠시 후
   * 다시」로 묶으면 로그인하면 된다는 사실을 아무도 알려주지 않는다 (#150).
   */
  | 'signed-out'
  /** 이미 종료된 세션 */
  | 'ended'
  /** 정원이 찬 세션 */
  | 'room-full'
  /** 409 인데 코드를 못 읽은 경우 — 두 사유를 합친 문구를 쓴다 */
  | 'unavailable'
  /** 그 외 (네트워크 포함) */
  | 'failed';

/* ---------------------------------------------------------------- *
 * 통화 중 (전사·추천 질문)
 *
 * LiveKit text stream irya.transcript.v1로 받는다.
 * ---------------------------------------------------------------- */

export interface Utterance {
  id: string;
  speaker: Speaker;
  text: string;
  atSec: number;
  final: boolean;
}

export type StreamEvent =
  | { type: 'speech.start'; speaker: Speaker; at: number }
  | { type: 'speech.end'; speaker: Speaker; at: number }
  | {
      type: 'transcript.delta';
      utteranceId: string;
      speaker: Speaker;
      text: string;
      at: number;
      final: boolean;
    }
  | { type: 'stream.degraded'; reason: string };

/* ---------------------------------------------------------------- *
 * 꼬리질문 (#212)
 *
 * 전사와 같은 방에서 오지만 통로가 다르다 — 전사는 text stream 이고
 * 꼬리질문은 BE 가 RoomService SendData 로 보내는 데이터 패킷이다.
 * 토픽 이름만 짝이고 받는 쪽 API 는 갈라진다 (lib/suggestionStream.ts).
 * ---------------------------------------------------------------- */

export interface Suggestion {
  /** 명세의 `suggestionId`. 실시간 패킷과 조회 응답을 이 값으로 합친다 */
  id: string;
  content: string;
  /** 서버가 받은 시각(ISO) */
  createdAt: string;
  /**
   * 면접관이 「이걸 묻겠다」고 눌러 둔 것. 누르면 새 꼬리질문이 와도 자리가 밀리지 않는다.
   *
   * 서버에는 없는 값이다 — 상태를 바꾸는 API 가 없어 화면 안에서만 산다.
   * 그래서 면접 중에 새로고침하면 풀린다.
   */
  pinned: boolean;
}
