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

const DEFAULT_PROFILE: MockContextProfile = {
  company: '엘리스',
  team: '플랫폼',
  role: '백엔드 엔지니어',
  talentProfile: '',
};

const STORAGE_KEY = 'irya:mock-context-profile:v1';

function loadContextProfile(): MockContextProfile {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null') as MockContextProfile;
    if (
      value &&
      typeof value.company === 'string' &&
      typeof value.team === 'string' &&
      typeof value.role === 'string' &&
      typeof value.talentProfile === 'string'
    ) {
      return value;
    }
  } catch {
    return { ...DEFAULT_PROFILE };
  }
  return { ...DEFAULT_PROFILE };
}

// 데모에서도 저장 후 새로고침하면 입력값을 다시 보여준다.
export const contextProfile: MockContextProfile = loadContextProfile();

export function saveContextProfile() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(contextProfile));
  } catch {
    return;
  }
}
