import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = ["/", "/compare", "/start", "/ask", "/methods"];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });
    for (const path of PAGES) {
      test(`no serious or critical accessibility violations on ${path}`, async ({ page }) => {
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        await page.goto(path);
        if (path === "/" || path === "/compare") await expect(page.locator(".verdict h2").first()).toBeVisible();
        else await page.waitForLoadState("load");
        await page.waitForTimeout(1500);
        const res = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .exclude(".maplibregl-canvas-container")
          .analyze();
        const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(bad.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
        expect(errors).toEqual([]);
      });
    }
  });
}

test("explore: verdict, chart, map, table view and downloads", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".verdict h2")).toContainText(/per decade|no clear trend|mixed/);
  await expect(page.getByRole("img", { name: /values from/ })).toBeVisible();
  await page.getByRole("button", { name: "Show table" }).first().click();
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "CSV" })).toHaveAttribute("href", /export\?format=csv/);
  const nb = await page.request.get(await page.getByRole("link", { name: /Notebook/ }).getAttribute("href") as string);
  expect(nb.ok()).toBeTruthy();
});

test("explore: search a place and switch modes", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".verdict h2")).toBeVisible();
  const box = page.getByRole("combobox", { name: "Where" });
  await box.fill("Brazil");
  await expect(page.getByRole("option", { name: /^Brazil · Country/ })).toBeVisible();
  await box.press("Enter"); // keyboard path: the first (active) option
  await expect(page.locator(".verdict h2")).toContainText("Brazil");
  await page.getByRole("button", { name: "Monthly anomalies" }).click();
  await expect(page.locator(".status-pill").first()).toBeVisible();
  await expect(page).toHaveURL(/mode=monthly/);
  await page.getByRole("button", { name: "Globe (3D)" }).click();
  await expect(page.getByRole("button", { name: "Globe (3D)" })).toHaveAttribute("aria-pressed", "true");
});

test("compare: difference test is shown", async ({ page }) => {
  await page.goto("/compare");
  await expect(page.locator(".verdict h2")).toContainText(/changing differently|no clear difference/);
  await expect(page.getByText(/minus/).first()).toBeVisible();
});

test("embed card renders without site chrome", async ({ page }) => {
  await page.goto("/");
  const href = await page.getByRole("link", { name: "Embeddable card" }).getAttribute("href");
  await page.goto(href as string);
  await expect(page.locator(".embed-card h1")).toBeVisible();
  await expect(page.locator(".site-header")).toHaveCount(0);
});

test("API keeps the strict Origin check behind the proxy", async ({ request }) => {
  const r = await request.post("/api/analysis/trend", { data: { variable: "temp_change", region: { place: "preset:globe" } }, headers: { Origin: "https://evil.example" } });
  expect(r.status()).toBe(403);
});
