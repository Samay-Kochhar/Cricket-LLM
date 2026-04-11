import { expect, test } from "@playwright/test";


test("chat workspace renders structured ODI result payload", async ({ page }) => {
  await page.route("**/api/query", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
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
        evidence_notes: [{ title: "Interpretation basis", detail: "Database only." }],
        citations: [{ label: "ODI batting summary", source_type: "database", locator: "analytics.deliveries_v1" }],
        insufficiencies: [],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("textbox").fill("Compare Virat Kohli and Steven Smith");
  await page.getByRole("button", { name: "Run ODI Query" }).click();

  await expect(page.getByText("Virat Kohli vs Steven Smith ODI comparison")).toBeVisible();
  await expect(page.getByText("ODI batting summary")).toBeVisible();
  await expect(page.getByRole("link", { name: /Compare Virat Kohli vs Steven Smith/i })).toBeVisible();
});
