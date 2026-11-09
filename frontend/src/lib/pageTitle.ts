const SITE = 'IRYA';

// 위에서부터 처음 맞는 것을 쓴다. 더 구체적인 경로를 먼저 둔다.
const TITLES: [RegExp, string][] = [
  [/^\/login\/?$/, '로그인'],
  [/^\/oauth\//, '로그인 중'],
  [/^\/terms\/?$/, '이용약관'],
  [/^\/privacy\/?$/, '개인정보처리방침'],
  [/^\/candidates\/?$/, '지원자 관리'],
  [/^\/settings\/context\/?$/, '기업 설정'],
  [/^\/interviews\/new\/?$/, '면접 만들기'],
  [/^\/interview\/[^/]+\/summary\/?$/, '면접 요약'],
  [/^\/interview\/[^/]+\/?$/, '면접'],
  [/^\/review\/[^/]+\/?$/, '면접 기록'],
  [/^\/report\/[^/]+\/?$/, '면접 리포트'],
];

/**
 * 화면마다 다른 문서 제목 (KWCAG 제목 제공). 탭 · 기록 · 화면낭독기가 지금 어느 화면인지
 * 알 수 있게 한다. 홈과 모르는 경로는 서비스 소개 제목을 그대로 쓴다.
 */
export function pageTitle(pathname: string): string {
  const hit = TITLES.find(([pattern]) => pattern.test(pathname));
  return hit ? `${hit[1]} | ${SITE}` : `${SITE} — 면접은 사람이, 정리는 AI가`;
}
