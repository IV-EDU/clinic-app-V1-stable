import { expect, test } from '@playwright/test';
import { loginAsAdmin } from './helpers';

test('login works and home route loads', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/');
  await expect(page.locator('meta[name="csrf-token"]')).toHaveCount(1);
  await expect(page.locator('table.patient-table, .no-patients').first()).toBeVisible();
});
