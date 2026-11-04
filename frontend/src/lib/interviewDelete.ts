/**
 * 면접 삭제 실패를 읽는다 (#246)
 *
 * 상태 코드만 받는다 — `ApiError` 를 값으로 들여오면 `api/client.ts` 가 따라 들어오고,
 * 그 안의 `import.meta.env` 때문에 node 테스트에서 모듈이 터진다.
 */

/** 지우지 못한 이유 */
export type DeleteFailure =
  /** 이미 없다. 목록만 맞추면 되는 일이라 화면은 지운 것으로 끝낸다 */
  | 'gone'
  /** 진행 중이거나 녹화를 합치는 중이다 */
  | 'busy'
  /** 토큰이 없거나 만료됐다 */
  | 'signed-out'
  /** 그 외 — 서버 · 네트워크 */
  | 'failed';

/** 응답을 못 받았으면(네트워크 · 프록시) status 가 없다. */
export function deleteFailure(status: number | undefined): DeleteFailure {
  // 남의 면접도 404 로 온다. 목록에는 자기 면접만 있으니 이미 지워진 것으로 읽는다.
  if (status === 404) return 'gone';
  if (status === 409) return 'busy';
  // 기다려서 되는 일이 아니다. 「잠시 후 다시」로 뭉개면 로그인하면 된다는 걸
  // 아무도 알려주지 않는다 (#150).
  if (status === 401) return 'signed-out';
  return 'failed';
}

export const DELETE_FAILURE_MESSAGE: Record<DeleteFailure, string> = {
  gone: '이미 지워진 면접입니다.',
  busy: '진행 중인 면접은 지울 수 없습니다. 면접을 끝낸 뒤 다시 시도해주세요.',
  'signed-out': '로그인이 풀렸습니다. 다시 로그인해주세요.',
  failed: '지우지 못했습니다. 잠시 후 다시 시도해주세요.',
};
