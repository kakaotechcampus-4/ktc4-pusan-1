import { expect, test } from '@playwright/test';
import { INTERVIEWS, mockApi, signIn } from './mockApi';

test('토큰이 있으면 지원자 목록을 서버 응답대로 그린다', async ({ page }) => {
  await signIn(page);
  await mockApi(page);

  await page.goto('/candidates');
  await expect(page).toHaveTitle('지원자 관리 | IRYA');
  await expect(page.getByText(INTERVIEWS.items[0].candidateName!).first()).toBeVisible();
});

test('만료된 토큰이면 지우고 로그인으로 보낸다', async ({ page }) => {
  await signIn(page, 'expired-token');
  await mockApi(page, { me: 401 });

  await page.goto('/candidates');
  await expect(page).toHaveURL(/\/login$/);
  // addInitScript 는 다음 이동 때 다시 심으므로, 지금 페이지에서 바로 읽는다.
  expect(await page.evaluate(() => localStorage.getItem('accessToken'))).toBeNull();
});
