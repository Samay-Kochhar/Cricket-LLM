import { expect, test } from "@playwright/test";
import type { VenueProfileResponse } from "../src/lib/api-types";

test("venue bowling filters drive ranking, chart, samples and table", async ({ page, request }) => {
  await page.goto("/venues/Feroz%20Shah%20Kotla%2C%20Delhi");
  await expect(page.getByRole("heading", { name: "Arun Jaitley Stadium, Delhi", exact: true })).toBeVisible();
  const control = (name: string) => page.getByRole("combobox", { name, exact: true });
  const number = (name: string) => page.getByRole("spinbutton", { name, exact: true });
  await expect(control("Venue")).toHaveValue("Arun Jaitley Stadium, Delhi");
  await expect(control("Venue").locator("option").filter({ hasText: "Feroz Shah Kotla" })).toHaveCount(0);
  await control("Rank and chart by").selectOption("economy_rate");
  await control("Phase").selectOption("middle");
  await control("Filter by").selectOption("matches");
  await number("Minimum number (0 = no minimum)").fill("1");
  await page.getByRole("checkbox").check();
  await number("From year").fill("2022");
  await number("Through year").fill("2023");
  await expect(page.getByRole("heading", { name: "Top Wicket Takers", exact: true })).toBeVisible();
  const loaded = page.waitForResponse((res) => res.url().includes("/api/venues/") && res.url().includes("metric=economy_rate"));
  await page.getByRole("button", { name: "Apply filter", exact: true }).click();
  const payload = await (await loaded).json() as VenueProfileResponse;
  await expect(page.getByRole("heading", { name: "Economy leaders", exact: true })).toBeVisible();
  await expect(page.getByText(/Active filters:/)).toContainText("Middle; 2022–2023; at least 1 distinct odi matches");
  expect(payload.ranking.direction).toBe("asc");
  const values = payload.bowling_leaderboard.map((row) => row.economy_rate!);
  expect(values).toEqual([...values].sort((a, b) => a - b));
  await expect(page.locator(".chart-value")).toHaveText(values.slice(0, 6).map((value) => String(Number(value.toFixed(2)))));
  await expect(page.locator("tbody tr").first()).toContainText(payload.bowling_leaderboard[0].player_name);
  for (const name of ["Deliveries", "Matches", "Runs", "Wickets", "Bowling average", "Economy", "Bowling strike rate", "Dot %", "Boundary % conceded"]) {
    await expect(page.getByRole("columnheader", { name, exact: true })).toBeVisible();
  }
  const chart = await page.getByRole("heading", { name: "Economy leaders", exact: true }).boundingBox();
  const table = await page.getByRole("heading", { name: "Bowling Leaderboard", exact: true }).boundingBox();
  expect(chart!.y).toBeLessThan(table!.y);
  await page.getByRole("checkbox").uncheck();
  const allYears = page.waitForResponse((res) => res.url().includes("metric=economy_rate") && !res.url().includes("year_start"));
  await page.getByRole("button", { name: "Apply filter", exact: true }).click();
  await allYears;
  await expect(page.getByText(/Active filters:/)).toContainText("Middle; All years");
  await expect(control("Rank and chart by")).toHaveValue("economy_rate");
  await expect(control("Phase")).toHaveValue("middle");
  await page.getByRole("button", { name: "Reset filter", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Top Wicket Takers", exact: true })).toBeVisible();
  await expect(control("Rank and chart by")).toHaveValue("wickets_taken");
  await expect(page.getByText(/Active filters:/)).toContainText("All phases; All years; at least 24 legal balls");
  const invalid = await request.get("/api/venues/in-delhi-kotla?year_start=2024&year_end=2023");
  expect(invalid.status()).toBe(422);
});
