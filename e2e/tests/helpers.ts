import { expect, Page } from '@playwright/test';

export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/auth/login');
  await expect(page.locator('form.login-form')).toBeVisible();
  await page.locator('input[name="username"]').fill('admin');
  await page.locator('input[name="password"]').fill('admin');
  await page.locator('form.login-form input[type="submit"], form.login-form button[type="submit"]').first().click();
  await expect(page).not.toHaveURL(/\/auth\/login/);
  await expect(page.locator('meta[name="csrf-token"]')).toHaveCount(1);
}
