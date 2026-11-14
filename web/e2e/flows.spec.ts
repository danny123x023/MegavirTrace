import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = ["/", "/compare", "/related", "/start", "/ask", "/methods"];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });
    for (const path of PAGES) {
      test(`no serious or critical accessibility violations on ${path}`, async ({ page }) => {
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        await page.goto(path);
        if (path === "/" || path === "/compare" || path === "/related") await expect(page.locator(".verdict h2").first()).toBeVisible();
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

test("moves together: verdict, lag chart and the not-a-cause caveat", async ({ page }) => {
  await page.goto("/related");
  await expect(page.locator(".verdict h2")).toContainText(/move together|No clear relationship/);
  await expect(page.getByText(/not caused by/).first()).toBeVisible();
  await expect(page.getByRole("img", { name: /Correlation by lag/ })).toBeVisible();
});

test("Spanish interface with a Spanish verdict from the server", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("mt-lang", "es"));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("¿De verdad está cambiando este lugar?");
  await expect(page.locator(".verdict h2")).toContainText(/por década|sin tendencia clara|evidencia es mixta/i);
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
});

test("works offline after one visit (production build)", async ({ page, context }) => {
  await page.goto("/?v=temp_change&place=admin1%3AUS-TX&label=Texas");
  await expect(page.locator(".verdict h2")).toBeVisible();
  const hasWorker = await page.evaluate(async () => {
    if (!("serviceWorker" in navigator) || (await navigator.serviceWorker.getRegistrations()).length === 0) return false;
    await navigator.serviceWorker.ready;
    return true;
  });
  test.skip(!hasWorker, "the service worker registers only in production builds");
  await page.reload();
  await expect(page.locator(".verdict h2")).toBeVisible();
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator(".verdict h2")).toContainText("Texas", { timeout: 15000 });
  await expect(page.locator(".offline-banner")).toBeVisible();
  await context.setOffline(false);
});

test("phone layout: nothing wider than the screen", async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto("/");
  await expect(page.locator(".verdict h2")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.close();
});

test("header: full-screen layout and dark mode switches apply and persist", async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, colorScheme: "light" });
  await page.goto("/methods");
  const html = page.locator("html");
  const mainWidth = () => page.locator("main").evaluate((e) => e.getBoundingClientRect().width);
  const full = () => page.getByRole("button", { name: "Full screen" });
  const dark = () => page.getByRole("button", { name: "Dark mode" });
  await expect(full()).toHaveAttribute("aria-pressed", "true"); // full width is the default
  await expect(dark()).toHaveAttribute("aria-pressed", "false"); // follows the device (light here)
  expect(await mainWidth()).toBeGreaterThan(1800);
  await full().click();
  await expect(html).toHaveAttribute("data-layout", "centered");
  expect(await mainWidth()).toBeLessThanOrEqual(1160);
  await dark().click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.reload(); // both choices are remembered and applied before paint
  await expect(html).toHaveAttribute("data-layout", "centered");
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(full()).toHaveAttribute("aria-pressed", "false");
  await expect(dark()).toHaveAttribute("aria-pressed", "true");
  await full().click();
  await dark().click();
  await expect(html).not.toHaveAttribute("data-layout", /.+/);
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.close();
});
