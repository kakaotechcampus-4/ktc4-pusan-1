import { useSyncExternalStore } from 'react';
import { readAccessToken, subscribeAccessToken } from '../lib/authToken';

export function useAccessToken() {
  return useSyncExternalStore(subscribeAccessToken, readAccessToken);
}
