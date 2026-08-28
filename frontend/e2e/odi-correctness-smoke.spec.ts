import { expect, test, type Page } from "@playwright/test";


test.describe("ODI correctness product-family smoke", () => {
  test.setTimeout(60_000);
  const chatInput = (page: Page) =>
    page.getByPlaceholder("Ask Atlas about a player, matchup, venue, or just talk cricket...");

  test("empty chat keeps the composer at the bottom", async ({ page }) => {
    await page.goto("/");

    const chatLogFlexGrow = await page.locator(".atlas-chat-log").evaluate(
      (element) => window.getComputedStyle(element).flexGrow,
    );

    expect(chatLogFlexGrow).toBe("1");
  });

  test("standalone question completes through the real chat API", async ({ page }) => {
    await page.goto("/");
    await chatInput(page).fill("What is Virat Kohli's batting strike rate against Australia?");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByText(/94\.0.*2518 balls/i).first()).toBeVisible();
    await expect(page.getByRole("cell", { name: "Virat Kohli", exact: true })).toBeVisible();
  });

  test("comparison question completes through the real chat API", async ({ page }) => {
    await page.goto("/");
    await chatInput(page).fill("Compare Virat Kohli and Rohit Sharma by runs scored.");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByRole("cell", { name: "Virat Kohli", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Rohit Sharma", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "13950", exact: true })).toBeVisible();
  });

  test("matchup question completes through the real chat API", async ({ page }) => {
    await page.goto("/");
    await chatInput(page).fill("Who has dismissed David Miller most often?");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByRole("cell", { name: "Suranga Lakmal", exact: true })).toBeVisible();
    await expect(page.getByText(/Suranga Lakmal ranks first/i).first()).toBeVisible();
  });

  test("named matchup paraphrase returns evidence and a supported pitch map", async ({ page }) => {
    await page.goto("/");
    await chatInput(page).fill("How did Steve Smith perform against Jasprit Bumrah?");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByText(/Steven Smith scored 103 runs from 121 balls/i).first()).toBeVisible();
    await expect(page.getByText(/2 dismissals.*85\.12/i).first()).toBeVisible();
    await expect(page.getByRole("cell", { name: "Jasprit Bumrah", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "ODI database", exact: true }).click();
    await expect(page.getByText("Line, length, strike rate, and wicket pressure")).toBeVisible();
  });

  test("contextual follow-up preserves state through the real chat API", async ({ page }) => {
    await page.goto("/");
    const input = chatInput(page);
    await input.fill("What is Virat Kohli's batting strike rate?");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText(/93\.51.*14918 balls/i).first()).toBeVisible();

    await input.fill("And in death overs?");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByText(/149\.9.*1016 balls/i).first()).toBeVisible();
  });

  test("yearly trend question shows cautious comparable evidence", async ({ page }) => {
    await page.goto("/");
    await chatInput(page).fill("Mitchell Starc death-over economy trend after 2018");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    await expect(page.getByText(/observed Economy Rate decreased from 7\.83 in 2018 to 7\.35 in 2023/i).first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText(/not a claim of statistical significance/i).first()).toBeVisible();
    await expect(page.getByText("Economy Rate by Year", { exact: true })).toBeVisible();
    const trendChart = page.getByRole("img", { name: "Economy Rate by Year line chart" });
    await expect(trendChart).toBeVisible();
    expect(await trendChart.locator(".simple-line-y-label").count()).toBeGreaterThanOrEqual(3);
    const axisY = Number(await trendChart.locator(".simple-line-x-axis").getAttribute("y1"));
    const pointYs = await trendChart.locator(".simple-line-point").evaluateAll((points) =>
      points.map((point) => Number(point.getAttribute("cy"))),
    );
    expect(Math.max(...pointYs)).toBeLessThan(axisY - 4);
    const yAxisX = Number(await trendChart.locator(".simple-line-axis").first().getAttribute("x1"));
    const firstValueBounds = await trendChart.locator(".simple-line-value").first().evaluate((label) => {
      const bounds = (label as SVGGraphicsElement).getBBox();
      return { left: bounds.x, right: bounds.x + bounds.width };
    });
    expect(firstValueBounds.left).toBeGreaterThan(yAxisX + 4);
    const chartRight = Number(await trendChart.locator(".simple-line-x-axis").getAttribute("x2"));
    const lastValueBounds = await trendChart.locator(".simple-line-value").last().evaluate((label) => {
      const bounds = (label as SVGGraphicsElement).getBBox();
      return { left: bounds.x, right: bounds.x + bounds.width };
    });
    expect(lastValueBounds.right).toBeLessThan(chartRight - 4);
    await expect(page.getByText("2018", { exact: true }).last()).toBeVisible();
    await expect(page.getByText("7.83", { exact: true }).last()).toBeVisible();
  });
});
