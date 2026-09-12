/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base URL. 미설정 시 api/client.ts 의 기본값을 쓴다. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
