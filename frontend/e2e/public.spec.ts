import { expect, test } from '@playwright/test';

test('로그인 전 홈은 랜딩을 보여 주고 시작하기가 로그인으로 간다', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle('IRYA — 면접은 사람이, 정리는 AI가');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('면접은 사람이');

  await page.getByRole('link', { name: '시작하기' }).first().click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page).toHaveTitle('로그인 | IRYA');
  await expect(page.getByRole('heading', { name: '면접관 로그인' })).toBeVisible();
  await expect(page.getByText('카카오 로그인')).toBeVisible();
});

for (const [path, title] of [
  ['/terms', '이용약관 | IRYA'],
  ['/privacy', '개인정보처리방침 | IRYA'],
] as const) {
  test(`${path} 는 로그인 없이 열린다`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page).toHaveTitle(title);
  });
}

test('로그인 안 한 채 면접관 화면에 들어오면 로그인으로 보낸다', async ({ page }) => {
  await page.goto('/candidates');
  await expect(page).toHaveURL(/\/login$/);
});
