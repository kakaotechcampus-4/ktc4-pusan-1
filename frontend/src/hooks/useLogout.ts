/**
 * 로그아웃 — 저장된 토큰을 지우는 것이 전부다. BE 에 로그아웃 API 가 없다(#119).
 * 토큰은 7일이면 만료되고 갱신 수단도 없어, 만료되면 다시 카카오 로그인을 거친다.
 */

import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { clearAccessToken } from '../lib/authToken';

export function useLogout() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  return () => {
    clearAccessToken();
    // 남은 응답을 지운다. 안 그러면 다음 사람이 로그인했을 때 이전 사람의 화면이 잠깐 보인다.
    qc.clear();
    void navigate('/login', { replace: true });
  };
}
