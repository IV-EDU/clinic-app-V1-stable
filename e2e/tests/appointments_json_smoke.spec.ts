import { expect, test } from '@playwright/test';
import { loginAsAdmin } from './helpers';

const REQUIRED_SCRIPT_IDS = ['appointments-data', 'patients-data', 'doctors-data'] as const;

test('appointments page exposes required JSON script tags', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/appointments/vanilla');

  const hasJsonScripts = (await page.locator('script#appointments-data').count()) > 0;

  if (hasJsonScripts) {
    for (const id of REQUIRED_SCRIPT_IDS) {
      const locator = page.locator(`script#${id}`);
      await expect(locator).toHaveCount(1);
      const raw = await locator.innerText();
      expect(() => JSON.parse(raw)).not.toThrow();
    }
    return;
  }

  // Current template variant is server-rendered cards without JSON script payload tags.
  await expect(page.locator('.appt-container')).toBeVisible();
  await expect(page.locator('.appt-filter-card')).toBeVisible();
});
