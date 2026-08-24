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

test("ambiguous strike rate can be clarified with a visible choice", async ({ page }) => {
  const messages: string[] = [];
  await page.route("**/api/chat", async (route) => {
    const request = route.request().postDataJSON() as { message: string };
    messages.push(request.message);
    const clarified = request.message.includes("bowling strike rate");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        clarified
          ? {
              mode: "analysis",
              message: "Jasprit Bumrah's Bowling Strike Rate is 28.4.",
              suggestions: [],
              clarification_options: [],
              activity_trace: ["ODI database"],
            }
          : {
              mode: "clarification",
              message: "Do you mean batting strike rate or bowling strike rate?",
              suggestions: [],
              clarification_options: [
                {
                  label: "Batting strike rate",
                  message: "What is Jasprit Bumrah's batting strike rate?",
                },
                {
                  label: "Bowling strike rate",
                  message: "What is Jasprit Bumrah's bowling strike rate?",
                },
              ],
              activity_trace: [],
            },
      ),
    });
  });

  await page.goto("/");
  await page.getByRole("textbox").fill("What is Jasprit Bumrah's strike rate?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("Do you mean batting strike rate or bowling strike rate?")).toBeVisible();

  await page.getByRole("button", { name: "Bowling strike rate", exact: true }).click();

  await expect.poll(() => messages).toEqual([
    "What is Jasprit Bumrah's strike rate?",
    "What is Jasprit Bumrah's bowling strike rate?",
  ]);
  await expect(page.getByText("Jasprit Bumrah's Bowling Strike Rate is 28.4.")).toBeVisible();
});

test("verified phase comparison suggestion sends the stored comparison state", async ({ page }) => {
  const requests: Array<{ message: string; conversation_state?: unknown }> = [];
  const suggestion = "Compare the same players in powerplay, middle, and death overs.";
  const conversationState = {
    players: ["Jasprit Bumrah", "Mitchell Starc"],
    metric: "economy_rate",
    comparison_participants: ["Jasprit Bumrah", "Mitchell Starc"],
    comparison_metrics: ["economy_rate", "bowling_strike_rate"],
    filters: { phase: "death" },
  };
  await page.route("**/api/chat", async (route) => {
    const request = route.request().postDataJSON() as {
      message: string;
      conversation_state?: unknown;
    };
    requests.push(request);
    const isFollowUp = request.message === suggestion;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        mode: "analysis",
        message: isFollowUp ? "Combined phase comparison ready." : "Death-over comparison ready.",
        suggestions: isFollowUp ? [] : [suggestion],
        clarification_options: [],
        conversation_state: conversationState,
        activity_trace: [],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("textbox").fill("Compare Bumrah and Starc in death overs");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.getByRole("button", { name: suggestion, exact: true }).click();

  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].message).toBe(suggestion);
  expect(requests[1].conversation_state).toEqual(conversationState);
  await expect(page.getByText("Combined phase comparison ready.")).toBeVisible();
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

test("bowling ranking exposes a legal-balls query threshold", async ({ page }) => {
  const messages: string[] = [];
  await page.route("**/api/chat", async (route) => {
    const request = route.request().postDataJSON() as { message: string };
    messages.push(request.message);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        mode: "analysis",
        message: "Bowling Strike Rate ranking ready.",
        query_response: {
          status: "supported",
          interpretation: {
            original_question: request.message,
            query_class: "venue_context_leaderboard",
            entities: [],
            filters: { semantic_metric: "bowling_strike_rate" },
          },
          summaries: [],
          tables: [
            {
              kind: "table",
              title: "Bowling strike-rate ranking",
              columns: ["Bowler", "Bowling Strike Rate", "Legal Balls"],
              rows: [["Charlie Cassell", 10.0, 70]],
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
  await page.getByRole("textbox").fill("Which bowler has the best bowling strike rate?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.getByLabel("Min legal balls").fill("100");
  await page.getByRole("button", { name: "Apply to query" }).click();

  await expect.poll(() => messages.length).toBe(2);
  expect(messages[1]).toBe(
    "Which bowler has the best bowling strike rate, minimum 100 legal balls",
  );
});
