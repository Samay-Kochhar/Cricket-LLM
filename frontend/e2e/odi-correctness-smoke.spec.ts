import { expect, test, type Page } from "@playwright/test";


test.describe("ODI correctness product-family smoke", () => {
  test.setTimeout(60_000);
  const chatInput = (page: Page) =>
    page.getByPlaceholder("Ask Atlas about a player, matchup, venue, or just talk cricket...");

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
});
