import { test, expect } from '@playwright/test';

const baseURL = process.env.VRT_BASE_URL;

if (!baseURL) {
  test.describe.configure({ mode: 'skip' });
}

test.describe('Visual smoke', () => {
  test('Customer login page', async ({ page }) => {
    await page.goto('/customer/login');
    await expect(page).toHaveScreenshot('customer-login.png');
  });

  test('Admin dashboard', async ({ page }) => {
    await page.goto('/admin/dashboard');
    await expect(page).toHaveScreenshot('admin-dashboard.png');
  });
});
