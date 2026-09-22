/**
 * 목 전용 기업 컨텍스트 보관소.
 *
 * 조회(mockApi.ts)와 저장(contextSettingsMock.ts)이 같은 값을 봐야 한다. 서로를 import 하면
 * 순환이 되므로 값만 이 파일에 둔다.
 *
 * ⚠️ BE 연동 시 이 파일과 두 목 파일을 함께 지운다.
 */

export interface MockContextProfile {
  company: string;
  team: string;
  /** 기본 직무 — 면접을 만들 때 초깃값으로 쓴다 */
  role: string;
  /** AI 면접관이 참고할 추가 인재상 */
  talentProfile: string;
}

export const contextProfile: MockContextProfile = {
  company: '엘리스',
  team: '플랫폼',
  role: '백엔드 엔지니어',
  talentProfile: '',
};
