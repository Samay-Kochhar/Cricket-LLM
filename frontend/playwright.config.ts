import { defineConfig } from "@playwright/test";


const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;


export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
    launchOptions: chromiumExecutablePath
      ? { executablePath: chromiumExecutablePath }
      : undefined,
  },
  webServer: [
    {
      command:
        "APP_ENV=development USE_SEMANTIC_ANALYTICS_V2=true SEMANTIC_V2_DEV_FALLBACK=true GEMINI_API_KEY= python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000",
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3000",
      port: 3000,
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
