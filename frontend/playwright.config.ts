import { defineConfig } from "@playwright/test";


const chromiumExecutablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT ?? "8000";
const frontendPort = process.env.PLAYWRIGHT_FRONTEND_PORT ?? "3000";
// The Python used to start the CricAtlas API (for example the
// odi-analyst-workbench Conda environment's interpreter).
const python = process.env.PLAYWRIGHT_PYTHON ?? "python";
const launchOptions = chromiumExecutablePath ? { executablePath: chromiumExecutablePath } : undefined;


export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: "on-first-retry",
    launchOptions,
  },
  projects: [
    {
      // Fast UI tests. Some intercept /api responses, so they are UI evidence
      // only, never proof of backend connectivity.
      name: "mocked",
      testIgnore: /\.integration\.spec\.ts$/,
    },
    {
      // Real network chain: browser -> Next same-origin proxy -> CricAtlas API.
      // These specs never intercept API endpoints.
      name: "integration",
      testMatch: /\.integration\.spec\.ts$/,
    },
  ],
  webServer: [
    {
      command:
        `APP_ENV=development USE_SEMANTIC_ANALYTICS_V2=true SEMANTIC_V2_DEV_FALLBACK=true GEMINI_API_KEY= ${python} -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: "..",
      url: `http://127.0.0.1:${backendPort}/health`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      // The proxy's one documented internal backend URL. No public API base
      // URL is set, so the browser must use the same-origin proxy.
      command: `BACKEND_INTERNAL_URL=http://127.0.0.1:${backendPort} NEXT_PUBLIC_API_BASE_URL= npm run dev -- --hostname 127.0.0.1 --port ${frontendPort}`,
      port: Number(frontendPort),
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
