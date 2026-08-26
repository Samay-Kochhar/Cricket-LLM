import { expect, test } from "@playwright/test";

function matchupPagePayload(balls = 121, lowSample = false, handedness = "RHB") {
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
        handedness,
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
  await expect(page.getByTestId("matchup-stat-batting-average")).toContainText("51.5");
  await expect(page.getByTestId("matchup-stat-strike-rate")).toContainText("85.12");
  await expect(page.getByTestId("matchup-stat-strike-rate")).toContainText("Batting SR");
  await expect(page.getByText("85.12 vs 93.51")).toBeVisible();
  await expect(page.getByText("Line, length, strike rate, and wicket pressure")).toBeVisible();
  await expect(page.getByRole("button", { name: "Avg", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "1-3", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Avg", exact: true }).click();
  await expect(page.locator('[title="Good length / On the stumps"]')).toContainText("20.0AVG");
  await expect(page.locator(".pitch-visual").getByText(/^1-3/)).toHaveCount(0);
  await expect(page.locator(".pitch-line-headers .pitch-axis-label")).toHaveText([
    "Wide outside off",
    "Outside off",
    "On the stumps",
    "Down leg",
  ]);
  await expect(page.getByText("Sample context")).not.toBeVisible();
});

test("matchup player fields suggest names while typing", async ({ page }) => {
  await page.route("**/api/matchups", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(matchupPagePayload()) });
  });
  await page.route("**/api/players/search?**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ query: "shik", items: ["Shikhar Dhawan"], count: 1 }),
    });
  });

  await page.goto("/matchups?batter=Steven%20Smith&bowler=Jasprit%20Bumrah");
  await page.getByRole("combobox", { name: "Batter" }).fill("shik");
  await expect(page.getByRole("option", { name: "Shikhar Dhawan" })).toBeVisible();
  await page.getByRole("option", { name: "Shikhar Dhawan" }).click();
  await expect(page.getByRole("combobox", { name: "Batter" })).toHaveValue("Shikhar Dhawan");
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
  await expect(page.getByText("Small sample: only 5 recorded balls, so treat these numbers as descriptive."))
    .toBeVisible();
  await expect(page.getByRole("heading", { name: "No pitch map shown" })).toBeVisible();
  await expect(page.getByText("Line, length, strike rate, and wicket pressure")).not.toBeVisible();
});

test("matchup pitch map mirrors for a left-handed batter and omits wide down leg", async ({ page }) => {
  await page.route("**/api/matchups", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(matchupPagePayload(93, false, "LHB")),
    });
  });

  await page.goto("/matchups?batter=Shikhar%20Dhawan&bowler=Mitchell%20Starc");

  await expect(page.locator(".pitch-line-headers .pitch-axis-label")).toHaveText([
    "Down leg",
    "On the stumps",
    "Outside off",
    "Wide outside off",
  ]);
  await expect(page.getByText("Wide Down Leg")).toHaveCount(0);
  await expect(page.locator(".pitch-grid-cell.empty")).toHaveCount(23);
  await expect(page.locator(".pitch-grid-cell.empty").first()).toHaveText("No deliveries");
  await expect(page.locator(".pitch-stumps.bowling")).toHaveCount(0);

  const alignment = await page.locator(".pitch-board").evaluate((board) => {
    const boardBox = board.getBoundingClientRect();
    const cells = board.querySelectorAll<HTMLElement>(".pitch-grid-row:first-child .pitch-grid-cell");
    const firstBox = cells[0].getBoundingClientRect();
    const lastBox = cells[cells.length - 1].getBoundingClientRect();
    const background = getComputedStyle(board, "::before");
    const onStumps = board.querySelector<HTMLElement>('[title="Good length / On the stumps"]');
    const stumps = board.querySelector<HTMLElement>(".pitch-stumps.batting");
    if (!onStumps || !stumps) throw new Error("Expected on-stumps cell and batting stumps");
    const onStumpsBox = onStumps.getBoundingClientRect();
    const stumpsBox = stumps.getBoundingClientRect();
    return {
      backgroundLeft: Number.parseFloat(background.left),
      backgroundRight: Number.parseFloat(background.right),
      cellsLeft: firstBox.left - boardBox.left,
      cellsRight: boardBox.right - lastBox.right,
      onStumpsCenter: (onStumpsBox.left + onStumpsBox.right) / 2,
      stumpsCenter: (stumpsBox.left + stumpsBox.right) / 2,
      offSideWidth: onStumpsBox.left - firstBox.left,
      legSideWidth: lastBox.right - onStumpsBox.right,
      boardAspectRatio: boardBox.width / boardBox.height,
      stumpHeight: stumpsBox.height,
    };
  });
  expect(Math.abs(alignment.backgroundLeft - alignment.cellsLeft)).toBeLessThan(2);
  expect(Math.abs(alignment.backgroundRight - alignment.cellsRight)).toBeLessThan(2);
  expect(Math.abs(alignment.onStumpsCenter - alignment.stumpsCenter)).toBeLessThan(2);
  expect(Math.abs(alignment.offSideWidth - alignment.legSideWidth)).toBeLessThan(2);
  expect(alignment.boardAspectRatio).toBeLessThan(1.5);
  expect(alignment.stumpHeight).toBeGreaterThanOrEqual(32);

  await expect(page.locator(".pitch-length-label")).toHaveText([
    "Full toss",
    "Yorker",
    "Full",
    "Good length",
    "Back of a length",
    "Short",
  ]);
  const lengthPlacement = await page.locator(".pitch-board").evaluate((board) => {
    const rows = board.querySelectorAll<HTMLElement>(".pitch-grid-row");
    const stumps = board.querySelector<HTMLElement>(".pitch-stumps.batting");
    if (!stumps) throw new Error("Expected batting stumps");
    const fullTossBox = rows[0].getBoundingClientRect();
    const yorkerBox = rows[1].getBoundingClientRect();
    const stumpsBox = stumps.getBoundingClientRect();
    return {
      fullTossCenter: (fullTossBox.top + fullTossBox.bottom) / 2,
      stumpCenter: (stumpsBox.top + stumpsBox.bottom) / 2,
      yorkerCenter: (yorkerBox.top + yorkerBox.bottom) / 2,
    };
  });
  expect(lengthPlacement.fullTossCenter).toBeLessThan(lengthPlacement.stumpCenter);
  expect(lengthPlacement.stumpCenter).toBeLessThan(lengthPlacement.yorkerCenter);
});

test("matchup explorer explains when an exact pair has zero ODI balls", async ({ page }) => {
  const payload = matchupPagePayload();
  payload.matchup.status = "insufficient_evidence";
  payload.matchup.summaries = [];
  payload.matchup.tables = [];
  payload.matchup.visuals = null;
  await page.route("**/api/matchups", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/matchups?batter=Shikhar%20Dhawan&bowler=Jasprit%20Bumrah");

  await expect(
    page.getByText(
      "No recorded ODI balls were found between Shikhar Dhawan and Jasprit Bumrah for these filters. Try another bowler or broaden the filters.",
    ),
  ).toBeVisible();
});
