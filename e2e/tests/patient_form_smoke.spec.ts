import { expect, test } from '@playwright/test';
import { loginAsAdmin } from './helpers';

test('new patient form loads expected fields and csrf token', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/patients/new');

  const patientForm = page.locator('form:has(input[name="full_name"])').first();
  await expect(page.locator('meta[name="csrf-token"]')).toHaveCount(1);
  await expect(patientForm.locator('input[name="csrf_token"]')).toHaveCount(1);
  await expect(patientForm.locator('input[name="full_name"]')).toBeVisible();
  await expect(patientForm.locator('input[name="phone"]')).toBeVisible();
});
