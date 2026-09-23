export type CandidateStatus = '대기' | '검토 중' | '확정';
export type FindingState = 'unreviewed' | 'adopted' | 'excluded';
export type CoverageState = 'confirmed' | 'partial' | 'missing';

export interface DemoFinding {
  id: string;
  title: string;
  source: string;
  quote: string;
  transcript: string;
  rationale: string;
  atSec: number | null;
  state: FindingState;
  uncertain?: boolean;
  correctedRange?: { startSec: number; endSec: number };
}

export interface DemoQuestion {
  id: string;
  atSec: number;
  label: string;
  question: string;
  answer: string;
  competency: string;
  bookmarked: boolean;
}

export interface DemoCandidate {
  id: string;
  name: string;
  role: string;
  years: number;
  interviewAt: string;
  interviewer: string;
  durationSec: number;
  status: CandidateStatus;
  coverage: { name: string; state: CoverageState }[];
  findings: DemoFinding[];
  questions: DemoQuestion[];
  summary: string[];
  memo: string;
  reviewHistory: { id: string; at: string; action: string }[];
}

export const DEMO_CANDIDATES: DemoCandidate[] = [
  {
    id: 'candidate-kim',
    name: '김도현',
    role: '백엔드 개발자',
    years: 4,
    interviewAt: '2026-09-18T05:00:00.000Z',
    interviewer: '박서연',
    durationSec: 634,
    status: '대기',
    coverage: [
      { name: '서비스 설계', state: 'confirmed' },
      { name: '성능 개선', state: 'partial' },
      { name: '협업', state: 'confirmed' },
      { name: '장애 대응', state: 'missing' },
    ],
    findings: [
      {
        id: 'kim-project-scope',
        title: '프로젝트 기여 범위',
        source: '지원서 · 프로젝트 1',
        quote: '팀 프로젝트에서 API와 프론트 화면을 함께 맡았습니다.',
        transcript: '배포 파이프라인은 제가 처음부터 구성했습니다.',
        rationale: '지원서의 담당 범위와 면접에서 말한 기여 범위를 나란히 확인합니다.',
        atSec: 405,
        state: 'unreviewed',
      },
      {
        id: 'kim-throughput',
        title: '처리량 수치의 근거',
        source: '지원서 · 성과 2',
        quote: '초당 2만 건의 이벤트를 안정적으로 처리했습니다.',
        transcript: '초당 2만 건까지 올렸는데 병목은 구체적으로 재보지 못했습니다.',
        rationale: '측정 환경과 병목 확인 과정이 답변에서 충분히 드러나지 않았습니다.',
        atSec: 118,
        state: 'unreviewed',
      },
      {
        id: 'kim-reliability',
        title: '전사 확인이 필요한 구간',
        source: '면접 전사 · 22:40',
        quote: '장애가 났을 때 재처리 큐로 복구했습니다.',
        transcript: '정확한 장애 원인과 재발 방지 조치는 확인되지 않았습니다.',
        rationale: '전사 신뢰도가 낮아 원본 음성에서 발언을 확인해야 합니다.',
        atSec: 262,
        state: 'unreviewed',
        uncertain: true,
      },
      {
        id: 'kim-ownership',
        title: '개인 기여 범위',
        source: '면접 답변 · Q4',
        quote: '팀에서 함께 설계했고 주요 기능은 제가 구현했습니다.',
        transcript: '어떤 기능을 직접 구현했는지 사례가 더 필요합니다.',
        rationale: '질문은 있었지만 개인이 맡은 범위가 구체적으로 확인되지 않았습니다.',
        atSec: 405,
        state: 'unreviewed',
      },
    ],
    questions: [
      {
        id: 'kim-q1',
        atSec: 15,
        label: '서비스 설계',
        question: '간단히 자기소개 부탁드립니다.',
        answer:
          '3년차 백엔드 개발자로, 실시간 스트리밍 파이프라인을 주로 맡아 왔다고 소개했습니다.',
        competency: '서비스 설계',
        bookmarked: false,
      },
      {
        id: 'kim-q2',
        atSec: 118,
        label: '개인 기여',
        question: '그 프로젝트에서 본인이 직접 맡은 부분은 어디까지인가요?',
        answer: 'API와 배포 구성을 맡았다고 했으나 역할 분담은 더 확인할 수 있습니다.',
        competency: '협업',
        bookmarked: true,
      },
      {
        id: 'kim-q3',
        atSec: 262,
        label: '성능 개선',
        question: '초당 2만 건을 처리할 때 병목은 어디였나요?',
        answer: '캐시 적중률은 기억나지 않는다고 답했습니다.',
        competency: '성능 개선',
        bookmarked: true,
      },
      {
        id: 'kim-q4',
        atSec: 405,
        label: '장애 대응',
        question: '최근에 대응한 장애와 복구 과정을 설명해 주세요.',
        answer: '재처리 큐를 사용했다고 했지만 원인과 재발 방지는 확인되지 않았습니다.',
        competency: '장애 대응',
        bookmarked: false,
      },
    ],
    summary: [
      '지원자는 트래픽 증가에 대응하며 캐시와 비동기 큐를 적용한 경험을 설명했습니다.',
      '처리량 수치의 측정 방법과 장애 후 재발 방지 과정은 원본 발언에서 더 확인할 수 있습니다.',
    ],
    memo: '팀 성과와 본인 기여 범위를 다음 면접에서 구분해 확인할 것.',
    reviewHistory: [],
  },
  {
    id: 'candidate-lee',
    name: '이재훈',
    role: '백엔드 개발자',
    years: 6,
    interviewAt: '2026-09-18T02:00:00.000Z',
    interviewer: '박서연',
    durationSec: 2823,
    status: '검토 중',
    coverage: [
      { name: '서비스 설계', state: 'confirmed' },
      { name: '성능 개선', state: 'confirmed' },
      { name: '협업', state: 'partial' },
      { name: '장애 대응', state: 'confirmed' },
    ],
    findings: [
      {
        id: 'lee-scope',
        title: '팀 간 역할 경계',
        source: '면접 답변 · Q3',
        quote: '플랫폼 팀과 협의하면서 API 계약을 맞췄습니다.',
        transcript: '최종 스키마 결정은 다른 팀과 함께 했습니다.',
        rationale: '공동 결정에서 후보자가 맡은 역할을 면접관이 확인합니다.',
        atSec: 960,
        state: 'adopted',
      },
      {
        id: 'lee-incident',
        title: '장애 복구 시간',
        source: '면접 답변 · Q5',
        quote: '복구까지 15분 정도 걸렸습니다.',
        transcript: '복구 시간의 기준 시점을 확인할 수 있습니다.',
        rationale: '장애 인지부터 정상화까지의 기준을 구분해 기록합니다.',
        atSec: 1510,
        state: 'unreviewed',
      },
    ],
    questions: [
      {
        id: 'lee-q1',
        atSec: 250,
        label: '시스템 설계',
        question: '서비스 경계는 어떤 기준으로 나눴나요?',
        answer: '변경 빈도와 소유 팀을 기준으로 경계를 정했다고 답했습니다.',
        competency: '서비스 설계',
        bookmarked: false,
      },
      {
        id: 'lee-q2',
        atSec: 960,
        label: '협업',
        question: '다른 팀과 API 계약을 맞춘 과정을 설명해 주세요.',
        answer: '스키마와 호환성 기준을 함께 정했다고 답했습니다.',
        competency: '협업',
        bookmarked: true,
      },
    ],
    summary: ['서비스 경계와 API 호환성 기준을 다른 팀과 합의한 사례를 설명했습니다.'],
    memo: '공동 작업에서 본인이 결정한 내용과 조율한 내용을 따로 메모함.',
    reviewHistory: [
      { id: 'lee-event-1', at: '2026-09-18T03:15:00.000Z', action: '근거 채택 · 팀 간 역할 경계' },
    ],
  },
  {
    id: 'candidate-park',
    name: '박수민',
    role: '플랫폼 엔지니어',
    years: 3,
    interviewAt: '2026-09-17T07:00:00.000Z',
    interviewer: '김도윤',
    durationSec: 3160,
    status: '확정',
    coverage: [
      { name: '서비스 설계', state: 'confirmed' },
      { name: '성능 개선', state: 'confirmed' },
      { name: '협업', state: 'confirmed' },
      { name: '장애 대응', state: 'partial' },
    ],
    findings: [
      {
        id: 'park-ownership',
        title: '자동화 범위',
        source: '면접 답변 · Q2',
        quote: '배포 전 검증 단계를 자동화했습니다.',
        transcript: '검증 작업 일부를 파이프라인으로 옮겼습니다.',
        rationale: '자동화 전후의 수작업 범위를 다시 확인합니다.',
        atSec: 642,
        state: 'adopted',
      },
    ],
    questions: [
      {
        id: 'park-q1',
        atSec: 642,
        label: '자동화',
        question: '자동화한 단계와 남겨 둔 수작업을 설명해 주세요.',
        answer: '배포 전 검증과 환경 확인을 파이프라인으로 옮겼다고 답했습니다.',
        competency: '성능 개선',
        bookmarked: false,
      },
    ],
    summary: ['배포 전 검증 절차를 자동화하고 운영 팀과 확인 기준을 맞춘 사례를 설명했습니다.'],
    memo: '확인된 근거와 다음에 확인할 부분을 정리했습니다.',
    reviewHistory: [{ id: 'park-event-1', at: '2026-09-17T08:10:00.000Z', action: '검토 확정' }],
  },
  {
    id: 'candidate-choi',
    name: '최유진',
    role: '백엔드 개발자',
    years: 5,
    interviewAt: '2026-09-16T05:30:00.000Z',
    interviewer: '김도윤',
    durationSec: 2890,
    status: '대기',
    coverage: [
      { name: '서비스 설계', state: 'confirmed' },
      { name: '성능 개선', state: 'partial' },
      { name: '협업', state: 'partial' },
      { name: '장애 대응', state: 'missing' },
    ],
    findings: [
      {
        id: 'choi-reliability',
        title: '장애 대응 사례',
        source: '면접 답변 · Q4',
        quote: '모니터링 알림을 받아 원인을 확인했습니다.',
        transcript: '장애 대응 이후 바꾼 점은 명확히 나오지 않았습니다.',
        rationale: '대응 뒤 운영 절차에 반영된 변경점을 확인할 수 있습니다.',
        atSec: 1320,
        state: 'unreviewed',
      },
      {
        id: 'choi-collab',
        title: '의견 조율 과정',
        source: '면접 답변 · Q2',
        quote: '서로의 제안을 비교해 합의했습니다.',
        transcript: '어떤 기준으로 합의했는지 전사가 불분명합니다.',
        rationale: '원본 구간에서 팀 의사결정 맥락을 확인합니다.',
        atSec: 770,
        state: 'unreviewed',
        uncertain: true,
      },
    ],
    questions: [
      {
        id: 'choi-q1',
        atSec: 370,
        label: '캐시 설계',
        question: '캐시 무효화는 어떤 방식으로 처리하셨나요?',
        answer: '갱신 주기와 무효화 이벤트를 함께 사용했다고 답했습니다.',
        competency: '서비스 설계',
        bookmarked: false,
      },
      {
        id: 'choi-q2',
        atSec: 770,
        label: '협업',
        question: '기술 선택이 갈렸던 상황에서 어떻게 합의했나요?',
        answer: '각 제안의 운영 비용을 비교했다고 답했습니다.',
        competency: '협업',
        bookmarked: false,
      },
    ],
    summary: ['캐시 무효화와 팀 내 기술 선택을 조율한 사례를 들었습니다.'],
    memo: '',
    reviewHistory: [],
  },
  {
    id: 'candidate-jung',
    name: '정민서',
    role: '플랫폼 엔지니어',
    years: 5,
    interviewAt: '2026-09-15T00:00:00.000Z',
    interviewer: '박서연',
    durationSec: 2952,
    status: '검토 중',
    coverage: [
      { name: '서비스 설계', state: 'partial' },
      { name: '성능 개선', state: 'confirmed' },
      { name: '협업', state: 'confirmed' },
      { name: '장애 대응', state: 'partial' },
    ],
    findings: [
      {
        id: 'jung-evidence',
        title: '응답 지연 개선 근거',
        source: '면접 답변 · Q1',
        quote: '응답 지연이 눈에 띄게 줄었습니다.',
        transcript: '비교한 기간과 측정 기준은 답변에 나오지 않았습니다.',
        rationale: '수치 대신 개선 전후 조건을 원본에서 확인합니다.',
        atSec: 420,
        state: 'unreviewed',
      },
    ],
    questions: [
      {
        id: 'jung-q1',
        atSec: 420,
        label: '성능 개선',
        question: '응답 지연은 어떤 조건에서 비교했나요?',
        answer: '인덱스를 보강하고 조회 요청을 분산했다고 답했습니다.',
        competency: '성능 개선',
        bookmarked: false,
      },
    ],
    summary: ['조회 경로를 분산해 지연을 줄인 사례를 설명했습니다.'],
    memo: '응답 지연 비교 조건을 추가로 물어볼 것.',
    reviewHistory: [],
  },
];

const STORAGE_KEY = 'irya:demo-review:v2';

export function loadDemoCandidates(): DemoCandidate[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredClone(DEMO_CANDIDATES);
    const parsed = JSON.parse(raw) as DemoCandidate[];
    if (
      !Array.isArray(parsed) ||
      !parsed.every(
        (candidate) =>
          typeof candidate.id === 'string' &&
          Array.isArray(candidate.findings) &&
          Array.isArray(candidate.questions) &&
          Array.isArray(candidate.coverage) &&
          Array.isArray(candidate.reviewHistory),
      )
    ) {
      return structuredClone(DEMO_CANDIDATES);
    }
    return parsed;
  } catch {
    return structuredClone(DEMO_CANDIDATES);
  }
}

export function saveDemoCandidates(candidates: DemoCandidate[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(candidates));
  } catch {
    return;
  }
}

export function resetDemoCandidates() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    return;
  }
}

export function findDemoCandidate(candidates: DemoCandidate[], id: string | undefined) {
  return candidates.find((candidate) => candidate.id === id);
}

export function updateDemoCandidate(
  candidates: DemoCandidate[],
  id: string,
  update: (candidate: DemoCandidate) => DemoCandidate,
) {
  return candidates.map((candidate) => (candidate.id === id ? update(candidate) : candidate));
}

export const formatDemoTime = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0')}`;

export const formatDemoDuration = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}분 ${remainingSeconds.toString().padStart(2, '0')}초`;
};
