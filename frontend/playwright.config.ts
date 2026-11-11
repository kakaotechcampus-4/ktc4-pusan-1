/**
 * 브라우저 E2E (#329).
 *
 * 빌드 결과를 `vite preview` 로 띄우고 실제 Chromium 으로 화면 흐름을 본다.
 * BE 는 띄우지 않는다 — 로그인이 카카오를 거쳐야 해서, 같이 띄우려면 테스트용 인증
 * 우회를 BE 에 만들어야 한다. 그건 만들지 않기로 했다. 로그인 뒤 화면은 `/api` 응답을
 * `e2e/mockApi.ts` 에서 모킹한다.
 */
import { defineConfig, devices } from '@playwright/test';

const PORT = 4173;

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // 운영 빌드는 VITE_API_BASE 가 없으면 같은 오리진의 /api 를 부른다. 모킹은 그 경로를 잡는다.
    // CI 는 앞 단계에서 이미 빌드했으니 그 dist 를 그대로 띄운다.
    command: `${process.env.CI ? '' : 'npm run build && '}npx vite preview --port ${PORT} --strictPort`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
