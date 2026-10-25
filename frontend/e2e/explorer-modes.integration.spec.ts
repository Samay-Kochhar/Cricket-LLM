import { expect, test } from "@playwright/test";
import type { CompareResponse, VenueProfileResponse } from "../src/lib/api-types";

test("Compare switches modes with shared context and chart metric", async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/compare?player=Mitchell%20Starc&player=Pat%20Cummins');
  await expect(page.getByRole('columnheader', { name: 'Batting average', exact: true })).toBeVisible();
  await page.getByRole('radio', { name: 'Bowling', exact: true }).check();
  await expect(page.getByRole('columnheader', { name: 'Economy', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Chart metric', exact: true }).selectOption('bowling_average');
  await page.getByRole('combobox', { name: 'Phase', exact: true }).selectOption('middle');
  await page.getByRole('combobox', { name: 'Venue', exact: true }).selectOption('Arun Jaitley Stadium, Delhi');
  await page.getByRole('checkbox').check();
  await page.getByRole('spinbutton', { name: 'From year', exact: true }).fill('2022');
  await page.getByRole('spinbutton', { name: 'Through year', exact: true }).fill('2023');
  const response = page.waitForResponse(r => r.url().includes('/api/compare?') && r.url().includes('metric=bowling_average'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  const profile = await (await response).json() as CompareResponse;
  await expect(page.getByText(/Active filters:/)).toContainText('Lower is preferable');
  expect(profile.filters).toEqual({ phase: 'middle', year_start: 2022, year_end: 2023, venue: 'Arun Jaitley Stadium, Delhi' });
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await expect(page.locator('.chart-value')).toHaveText(profile.players.filter(p => p.bowling_average != null).map(p => String(Number(p.bowling_average!.toFixed(2)))));
  await page.getByRole('radio', { name: 'Batting', exact: true }).check();
  await expect(page.getByRole('columnheader', { name: 'Batting average', exact: true })).toBeVisible();
  await expect(page.getByText(/Active filters:/)).toContainText('Middle; 2022–2023; Arun Jaitley Stadium, Delhi');
  await page.getByRole('button', { name: 'Reset filter', exact: true }).click();
  await expect(page.getByText(/Active filters:/)).toContainText('All phases; All years; All venues');
  expect(errors).toEqual([]);
});

test("Venue batting rankings preserve context, metric direction and chart-first order", async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/venues/Feroz%20Shah%20Kotla%2C%20Delhi');
  await expect(page.getByRole('heading', { name: 'Top Wicket Takers', exact: true })).toBeVisible();
  await page.getByRole('radio', { name: 'Batting', exact: true }).check();
  await expect(page.getByRole('heading', { name: 'Batting Leaderboard', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Rank and chart by', exact: true }).selectOption('batter_dot_percentage');
  await page.getByRole('combobox', { name: 'Phase', exact: true }).selectOption('middle');
  await page.getByRole('spinbutton', { name: 'Minimum number (0 = no minimum)', exact: true }).fill('1');
  await page.getByRole('checkbox').check();
  await page.getByRole('spinbutton', { name: 'From year', exact: true }).fill('2022');
  await page.getByRole('spinbutton', { name: 'Through year', exact: true }).fill('2023');
  const response = page.waitForResponse(r => r.url().includes('/api/venues/') && r.url().includes('metric=batter_dot_percentage'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  const profile = await (await response).json() as VenueProfileResponse;
  await expect(page.getByRole('heading', { name: 'Dot-ball % leaders', exact: true })).toBeVisible();
  expect(profile.mode).toBe('batting');
  const values = profile.leaderboard.map(p => p.dot_percentage!);
  expect(values.length).toBeGreaterThan(0);
  expect(values).toEqual([...values].sort((a, b) => a - b));
  await expect(page.locator('.chart-value')).toHaveText(values.slice(0, 6).map(v => String(Number(v.toFixed(2)))));
  for (const name of ['Balls faced', 'Runs', 'Dismissals', 'Batting average', 'Strike rate', 'Control %', 'Control balls', 'Dot %', 'Boundary %']) {
    await expect(page.getByRole('columnheader', { name, exact: true })).toBeVisible();
  }
  const chart = await page.getByRole('heading', { name: 'Dot-ball % leaders', exact: true }).boundingBox();
  const table = await page.getByRole('heading', { name: 'Batting Leaderboard', exact: true }).boundingBox();
  expect(chart!.y).toBeLessThan(table!.y);
  await page.getByRole('radio', { name: 'Bowling', exact: true }).check();
  await expect(page.getByRole('heading', { name: 'Bowling Leaderboard', exact: true })).toBeVisible();
  await expect(page.getByText(/Active filters:/)).toContainText('Middle; 2022–2023; at least 1 legal balls');
  await page.getByRole('radio', { name: 'Batting', exact: true }).check();
  await expect(page.getByRole('heading', { name: 'Batting Leaderboard', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Reset filter', exact: true }).click();
  await expect(page.getByText(/Active filters:/)).toContainText('All phases; All years; at least 24 balls faced');
  expect(errors).toEqual([]);
});
