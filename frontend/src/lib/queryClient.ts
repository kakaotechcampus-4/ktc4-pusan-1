/**
 * TanStack Query 설정.
 *
 * 기본값을 여기서 한 번만 정해 화면마다 같은 규칙이 적용되게 한다.
 */

import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 창을 다시 눌렀다고 조회를 새로 하지 않는다.
      // 면접 중에 탭을 오가는 일이 잦은데, 그때마다 재조회하면 불필요한 요청이 쌓인다.
      refetchOnWindowFocus: false,

      // 실패하면 한 번만 더 시도한다. 기본값(3회)은 네트워크가 끊겼을 때
      // 에러 화면이 뜨기까지 너무 오래 걸린다.
      retry: 1,

      // 폴링으로 상태가 바뀌는 데이터가 많아 오래 신선하다고 보지 않는다.
      staleTime: 0,

      // 탭이 백그라운드여도 폴링을 이어간다.
      // 기본값(false)이면 다른 탭을 보는 동안 인터벌이 멈춘다. 문서 파싱과 요약 생성은
      // 서버에서 계속 진행되므로, 돌아왔을 때 이미 끝나 있는 편이 자연스럽다.
      refetchIntervalInBackground: true,
    },
    mutations: {
      // 쓰기는 재시도하지 않는다. 면접 생성이 두 번 일어나면 안 된다.
      retry: 0,
    },
  },
});
