import { expect, test } from "@playwright/test";


test("player explorer renders ODI profile payload", async ({ page }) => {
  await page.route("**/api/players/**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        player_name: "Virat Kohli",
        summary: {
          player_name: "Virat Kohli",
          balls_faced: 280,
          runs_scored: 300,
          strike_rate: 107.14,
          control_percentage: 82.4,
        },
        trend: [
          { year: 2023, balls_faced: 100, runs_scored: 110, control_percentage: 80.2 },
          { year: 2024, balls_faced: 180, runs_scored: 190, control_percentage: 83.7 },
        ],
        suggestions: [],
      }),
    });
  });

  await page.goto("/players/Virat%20Kohli");

  await expect(page.getByRole("heading", { name: "Virat Kohli" })).toBeVisible();
  await expect(page.getByText("Batting Snapshot")).toBeVisible();
  await expect(page.getByText("Runs by year")).toBeVisible();
});
