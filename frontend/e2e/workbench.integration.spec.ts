import { expect, test, type Page } from "@playwright/test";


/**
 * Real-browser Workbench smoke (issue 46).
 *
 * Nothing here intercepts API endpoints: every search travels browser ->
 * same-origin Next proxy -> CricAtlas backend -> DuckDB. Natural-language
 * analytics must use the shared Semantic V2 meaning, while exact player and
 * team lookups keep their approved structured result modes.
 */

async function searchWorkbench(page: Page, query: string) {
  const input = page.getByPlaceholder("Search players, teams, countries, or ODI questions...");
  await input.fill(query);
  const response = page.waitForResponse(
    (item) => new URL(item.url()).pathname === "/api/workbench/search",
  );
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const received = await response;
  expect(received.status()).toBe(200);
  return (await received.json()) as { kind: string; player_name?: string };
}

test.describe("Workbench routing through shared semantic meaning", () => {
  test.setTimeout(60_000);

  test.beforeEach(async ({ page }) => {
    await page.goto("/workbench");
  });

  test("a best-bowlers ranking is analytics, never the player Tino Best", async ({ page }) => {
    const payload = await searchWorkbench(page, "Show the best death-over bowlers with at least 300 balls");

    expect(payload.kind).toBe("analytics_result");
    expect(payload.player_name).toBeUndefined();
    await expect(page.getByText("Resolved question")).toBeVisible();
    await expect(page.getByText("Resolved player")).toHaveCount(0);
    await expect(page.getByText("Tino Best")).toHaveCount(0);
  });

  test("a head-to-head question routes to the batter-bowler matchup", async ({ page }) => {
    const payload = await searchWorkbench(page, "Kohli versus Starc head to head");

    expect(payload.kind).toBe("analytics_result");
    await expect(
      page.getByText(/Virat Kohli scored 156 runs from 155 balls against Mitchell Starc/i),
    ).toBeVisible();
    await expect(page.getByText("Resolved player")).toHaveCount(0);
  });

  test("a two-player death-overs comparison keeps both players", async ({ page }) => {
    const payload = await searchWorkbench(page, "Compare Virat Kohli and Rohit Sharma in death overs");

    expect(payload.kind).toBe("analytics_result");
    await expect(page.getByText(/Virat Kohli scored more runs than Rohit Sharma: 1523 vs 1107/i)).toBeVisible();
  });

  test("an exact player lookup keeps the approved player result", async ({ page }) => {
    const payload = await searchWorkbench(page, "Virat Kohli");

    expect(payload.kind).toBe("player_result");
    await expect(page.getByText("Resolved player")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Virat Kohli", exact: true })).toBeVisible();
    await expect(page.getByText(/Right-hand bat \| ODI batter profile/)).toBeVisible();
  });

  test("an ambiguous surname offers targeted player choices", async ({ page }) => {
    const payload = await searchWorkbench(page, "Sharma");

    expect(payload.kind).toBe("clarification");
    await expect(page.getByText("Which player do you mean?")).toBeVisible();
    await expect(page.getByRole("button", { name: "Ishant Sharma", exact: true })).toBeVisible();

    const response = page.waitForResponse(
      (item) => new URL(item.url()).pathname === "/api/workbench/search",
    );
    await page.getByRole("button", { name: "Rohit Sharma", exact: true }).click();
    expect((await (await response).json()).kind).toBe("player_result");
    await expect(page.getByRole("heading", { name: "Rohit Sharma", exact: true })).toBeVisible();
  });

  test("a team asks for a year and then returns the squad", async ({ page }) => {
    const payload = await searchWorkbench(page, "India");

    expect(payload.kind).toBe("team_year_required");
    await expect(page.getByText("Year needed")).toBeVisible();

    const response = page.waitForResponse(
      (item) => new URL(item.url()).pathname === "/api/workbench/search",
    );
    await page.getByRole("button", { name: "2019", exact: true }).click();
    expect((await (await response).json()).kind).toBe("team_squad");
    await expect(page.getByText("Resolved squad")).toBeVisible();
    await expect(page.getByRole("heading", { name: "India 2019" })).toBeVisible();
  });
});
