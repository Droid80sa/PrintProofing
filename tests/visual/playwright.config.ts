import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.VRT_BASE_URL;

export default defineConfig({
  testDir: './tests/visual/specs',
  outputDir: './tests/visual/artifacts',
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
