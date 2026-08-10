import AxeBuilder from "@axe-core/playwright";

import { expect, test } from "./fixtures";

test("states the production boundary beside the operational state", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Evidence begins with refusal." }),
  ).toBeVisible();
  await expect(page.getByText("Not yet in production", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Refused until the pipeline exists", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Foundation services ready")).toBeVisible();
});

test("has a keyboard-visible skip target", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to system state" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeInViewport();
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Foundation services ready")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
