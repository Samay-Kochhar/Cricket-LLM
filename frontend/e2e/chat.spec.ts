import { expect, test } from "@playwright/test";


test("chat workspace renders structured ODI result payload", async ({ page }) => {
  await page.route("**/api/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        mode: "database",
        message: "Virat Kohli vs Steven Smith ODI comparison",
        query_response: {
          status: "supported",
          interpretation: {
            original_question: "Compare Virat Kohli and Steven Smith",
            query_class: "role_comparison",
            entities: ["Virat Kohli", "Steven Smith"],
            filters: {},
          },
          summaries: [
            {
              kind: "summary",
              title: "Virat Kohli vs Steven Smith ODI comparison",
              body: "Virat Kohli leads strike rate while Steven Smith remains highly controlled.",
            },
          ],
          tables: [],
          charts: [],
          metric_references: [],
          evidence_queries: [],
          evidence_notes: [{ title: "Interpretation basis", detail: "Database only." }],
          citations: [{ label: "ODI batting summary", source_type: "database", locator: "analytics.deliveries_v1" }],
          insufficiencies: [],
        },
        suggestions: [],
        activity_trace: ["ODI database"],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("textbox").fill("Compare Virat Kohli and Steven Smith");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  await expect(page.getByText("Virat Kohli vs Steven Smith ODI comparison")).toBeVisible();
  await page.getByRole("button", { name: "ODI database", exact: true }).click();
  await page.getByText("Metrics, notes, and citations", { exact: true }).click();
  await expect(page.getByText("ODI batting summary")).toBeVisible();
  await expect(page.getByRole("button", { name: "Go to Workbench" })).toBeVisible();
});

test("minimum-balls control reruns the database query instead of filtering limited rows", async ({ page }) => {
  const messages: string[] = [];
  await page.route("**/api/chat", async (route) => {
    const request = route.request().postDataJSON() as { message: string };
    messages.push(request.message);
    const isRefined = request.message.includes("minimum 100 balls");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        mode: "database",
        message: isRefined
          ? "Bernard Scholtz has the best qualifying death-over economy."
          : "Charith Asalanka has the best death-over economy in the initial sample.",
        query_response: {
          status: "supported",
          interpretation: {
            original_question: request.message,
            query_class: "venue_context_leaderboard",
            entities: [],
            filters: { phase: "death" },
          },
          summaries: [],
          tables: [
            {
              kind: "table",
              title: "Death-over economy",
              columns: ["Bowler", "Economy Rate", "Balls"],
              rows: isRefined
                ? [["Bernard Scholtz", 4.0, 240]]
                : [["Charith Asalanka", 2.29, 55]],
            },
          ],
          charts: [],
          metric_references: [],
          evidence_queries: [],
          evidence_notes: [],
          citations: [],
          insufficiencies: [],
        },
        suggestions: [],
        activity_trace: ["ODI database"],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("textbox").fill("Who has the least economy in death overs?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.getByLabel("Min balls").fill("100");
  await page.getByRole("button", { name: "Apply to query" }).click();

  await expect.poll(() => messages.length).toBe(2);
  expect(messages[1]).toBe("Who has the least economy in death overs, minimum 100 balls");
  await expect(page.locator(".chat-turn.user")).toHaveCount(1);
  await expect(page.locator(".chat-turn.assistant")).toHaveCount(1);
  await expect(page.getByRole("cell", { name: "Bernard Scholtz" })).toBeVisible();
  await expect(page.getByText("Charith Asalanka")).toHaveCount(0);
});
