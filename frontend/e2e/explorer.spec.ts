import { expect, test } from "@playwright/test";

function matchupPagePayload(balls = 121, lowSample = false) {
  const common = {
    status: "supported",
    charts: [],
    metric_references: [],
    evidence_queries: [],
    evidence_notes: [],
    citations: [],
    insufficiencies: [],
  };
  return {
    matchup: {
      ...common,
      interpretation: { original_question: "Structured matchup", query_class: "matchup", entities: [], filters: {} },
      summaries: [{ kind: "summary", title: "Answer", body: lowSample ? `Low sample: ${balls} balls.` : "Steven Smith scored 103 runs from 121 balls and was dismissed twice by Jasprit Bumrah." }],
      tables: [{
        kind: "table",
        title: "Steven Smith vs Jasprit Bumrah",
        columns: ["Batter", "Bowler", "Balls", "Runs", "Dismissals", "Batting Strike Rate", "Batter Dot Ball Percentage", "Boundary Percentage", "False Shot Percentage"],
        rows: [["Steven Smith", "Jasprit Bumrah", balls, lowSample ? 4 : 103, lowSample ? 0 : 2, lowSample ? 80 : 85.12, 48.76, 8.26, 22.31]],
      }],
      visuals: { pitch_map: {
        kind: "pitch_map",
        coverage: { total_balls: balls, covered_balls: balls, coverage_percentage: 100, detail: "Complete coverage." },
        cells: [{ line: "ON_THE_STUMPS", length: "GOOD_LENGTH", balls, runs: 20, strike_rate: 66.67, dismissals: 1, boundary_balls: 2, dot_balls: 17, singles: 9, doubles: 1, triples: 0, fours: 2, sixes: 0, wicket_balls: 1, control_percentage: 75 }],
      } },
    },
    baseline: {
      ...common,
      interpretation: { original_question: "Structured baseline", query_class: "aggregate", entities: [], filters: {} },
      summaries: [{ kind: "summary", title: "Baseline", body: "Steven Smith's overall rate is 93.51." }],
      tables: [{ kind: "table", title: "Steven Smith overall", columns: ["Batter", "Batting Strike Rate"], rows: [["Steven Smith", 93.51]] }],
      visuals: null,
    },
  };
}


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

test("matchup explorer answers a named batter versus bowler question", async ({ page }) => {
  await page.route("**/api/matchups", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(matchupPagePayload()) });
  });

  await page.goto("/matchups?batter=Steven%20Smith&bowler=Jasprit%20Bumrah");

  await expect(page.getByRole("heading", { name: "Steven Smith vs Jasprit Bumrah" })).toBeVisible();
  await expect(page.getByTestId("matchup-stat-runs")).toContainText("103");
  await expect(page.getByTestId("matchup-stat-balls")).toContainText("121");
  await expect(page.getByTestId("matchup-stat-dismissals")).toContainText("2");
  await expect(page.getByTestId("matchup-stat-strike-rate")).toContainText("85.12");
  await expect(page.getByText("85.12 vs 93.51")).toBeVisible();
  await expect(page.getByText("Line, length, strike rate, and wicket pressure")).toBeVisible();
});

test("matchup filters form a specific question and protect low samples", async ({ page }) => {
  await page.route("**/api/matchups", async (route) => {
    const body = route.request().postDataJSON() as { phase: string };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(matchupPagePayload(body.phase === "death" ? 5 : 121, body.phase === "death")) });
  });

  await page.goto("/matchups?batter=Steven%20Smith&bowler=Jasprit%20Bumrah");
  await page.getByLabel("Phase").selectOption("death");
  await page.getByLabel("Year").fill("2023");
  await page.getByLabel("Venue").fill("Sydney Cricket Ground");
  const filteredRequest = page.waitForRequest((request) => {
    const body = request.postDataJSON() as { phase?: string } | null;
    return request.url().includes("/api/matchups") && body?.phase === "death";
  });
  await page.getByRole("button", { name: "Show matchup" }).click();

  const request = await filteredRequest;
  expect(request.postDataJSON()).toEqual({
    batter: "Steven Smith",
    bowler: "Jasprit Bumrah",
    phase: "death",
    year: 2023,
    venue: "Sydney Cricket Ground",
  });
  await expect(page).toHaveURL(/phase=death.*year=2023.*venue=Sydney\+Cricket\+Ground/);
  await expect(page.getByRole("heading", { name: "Treat this as a small sample" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No pitch map shown" })).toBeVisible();
  await expect(page.getByText("Line, length, strike rate, and wicket pressure")).not.toBeVisible();
});
