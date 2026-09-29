import { expect, test, type Page, type Request } from "@playwright/test";


/**
 * Integration evidence for the browser routing policy (issue 45).
 *
 * Nothing here intercepts API endpoints. Every CricAtlas request must travel
 * browser -> same-origin Next proxy -> CricAtlas backend, and no browser
 * request may go to a guessed backend host such as port 8000.
 */

function trackApiRequests(page: Page) {
  const requests: Request[] = [];
  const failures: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) {
      requests.push(request);
    }
  });
  page.on("requestfailed", (request) => {
    failures.push(`${request.url()} ${request.failure()?.errorText ?? ""}`);
  });
  page.on("console", (message) => {
    if (/CORS|Failed to fetch/i.test(message.text())) {
      failures.push(message.text());
    }
  });
  return { requests, failures };
}

function expectSameOrigin(page: Page, requests: Request[], path: string) {
  const origin = new URL(page.url()).origin;
  const matching = requests.filter((request) => new URL(request.url()).pathname === path);
  expect(matching.length, `${path} was requested`).toBeGreaterThan(0);
  for (const request of requests) {
    expect(new URL(request.url()).origin, request.url()).toBe(origin);
  }
}


test.describe("browser -> frontend proxy -> CricAtlas backend", () => {
  test.setTimeout(90_000);

  test("chat reaches the real backend through the same-origin proxy", async ({ page }) => {
    const { requests, failures } = trackApiRequests(page);
    await page.goto("/");
    await page
      .getByPlaceholder("Ask Atlas about a player, matchup, venue, or just talk cricket...")
      .fill("What is Virat Kohli's batting strike rate against Australia?");
    const response = page.waitForResponse((item) => new URL(item.url()).pathname === "/api/chat");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const chat = await response;
    expect(chat.status()).toBe(200);
    await expect(page.getByText(/94\.0.*2518 balls/i).first()).toBeVisible();
    expectSameOrigin(page, requests, "/api/chat");
    expect(failures).toEqual([]);
  });

  test("matchups loads Steven Smith versus Jasprit Bumrah from the real backend", async ({ page }) => {
    const { requests, failures } = trackApiRequests(page);
    const response = page.waitForResponse((item) => new URL(item.url()).pathname === "/api/matchups");
    await page.goto("/matchups?batter=Steven%20Smith&bowler=Jasprit%20Bumrah");

    expect((await response).status()).toBe(200);
    await expect(page.getByText(/Steven Smith scored 103 runs from 121 balls/i).first()).toBeVisible();
    await expect(page.getByText("Failed to fetch")).toHaveCount(0);
    expectSameOrigin(page, requests, "/api/matchups");
    expect(failures).toEqual([]);
  });

  test("workbench loads a real player query from the real backend", async ({ page }) => {
    const { requests, failures } = trackApiRequests(page);
    await page.goto("/workbench");
    await page
      .getByPlaceholder("Search players, teams, countries, or ODI questions...")
      .fill("death over strike rate of Hardik Pandya");
    const response = page.waitForResponse(
      (item) => new URL(item.url()).pathname === "/api/workbench/search",
    );
    await page.getByRole("button", { name: "Search", exact: true }).click();

    expect((await response).status()).toBe(200);
    await expect(page.getByText("Hardik Pandya").first()).toBeVisible();
    await expect(page.getByText("Failed to fetch")).toHaveCount(0);
    expectSameOrigin(page, requests, "/api/workbench/search");
    expect(failures).toEqual([]);
  });
});
