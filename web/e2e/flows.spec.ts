import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = ["/", "/compare", "/related", "/start", "/cases", "/cases/europe-heatwave-2003", "/ask", "/methods", "/imports"];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });
    for (const path of PAGES) {
      test(`no serious or critical accessibility violations on ${path}`, async ({ page }) => {
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        await page.goto(path);
        if (path === "/" || path === "/compare" || path === "/related") await expect(page.locator(".verdict h2").first()).toBeVisible();
        else if (path.startsWith("/cases")) await expect(page.locator(".case-card, .case-step").first()).toBeVisible();
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

test("phone layout: nothing wider than the screen, every page link in view", async ({ browser }) => {
  for (const width of [360, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 844 } });
    await page.goto("/");
    await expect(page.locator(".verdict h2")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    const links = page.getByRole("navigation", { name: "Main" }).getByRole("link");
    await expect(links).toHaveCount(8);
    for (const link of await links.all()) {
      await expect(link).toBeInViewport({ ratio: 1 });
    }
    // the theme switch keeps a visible word on phones, and its full name
    await expect(page.getByRole("button", { name: "Dark mode" })).toContainText("Dark");
    await page.close();
  }
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

test("data import dashboard: NASA sources, history and stored data (read-only)", async ({ page }) => {
  await page.goto("/imports");
  await expect(page.getByRole("heading", { name: "Data import dashboard" })).toBeVisible();
  for (const h of ["NASA Earthdata account", "1. Available from NASA", "2. Import progress", "3. In the database"]) {
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  }
  // every source is listed; GISTEMP is stored as real data in every test setup
  const sources = page.locator("#cat-h").locator("xpath=ancestor::section").locator("tbody tr");
  await expect(sources).toHaveCount(17);
  const stored = page.locator("#db-h").locator("xpath=ancestor::section");
  await expect(stored.getByRole("row", { name: /Surface temperature change/ })).toContainText("Real NASA data");
  await stored.getByRole("button", { name: /^Nothing stored/ }).click();
  await expect(stored.getByRole("row", { name: /Surface temperature change/ })).toHaveCount(0);
  // the web app's proxy hides the visitor's address, so even on the server the page needs the token
  await expect(page.getByText("Viewing only: imports need the administrator token")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Administrator sign-in" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Import selected/ })).toBeDisabled();
  await page.getByLabel("Administrator token").fill("not-the-token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("That token is not right.")).toBeVisible();
});


test("every result card can go full screen and back", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".verdict h2")).toBeVisible();
  await expect(page.getByRole("button", { name: "Show full screen" })).not.toHaveCount(0);
  const map = page.locator("section[aria-label='Where inside the region']");
  const before = await map.locator(".map-box").evaluate((e) => e.getBoundingClientRect().height);
  await map.getByRole("button", { name: "Show full screen" }).click();
  await expect(map).toHaveClass(/is-full/);
  expect(await map.locator(".map-box").evaluate((e) => e.getBoundingClientRect().height)).toBeGreaterThan(before);
  await map.getByRole("button", { name: "Exit full screen" }).click();
  await expect(map).not.toHaveClass(/is-full/);
  // charts carry the switch in their header, next to "Show table"
  const chart = page.locator("section[aria-label='Time series']");
  await chart.getByRole("button", { name: "Show full screen" }).click();
  await expect(chart).toHaveClass(/is-full/);
  await chart.getByRole("button", { name: "Exit full screen" }).click();
  await expect(chart).not.toHaveClass(/is-full/);
});

test.describe("map base layers", () => {
  // the service worker would answer the map requests itself, out of reach of page.route
  test.use({ serviceWorkers: "block" });
  test("map: street map with location and scale; country outlines when it cannot load", async ({ page }) => {
    // a stand-in street-map style (the real one is relayed from OpenStreetMap tiles by the API)
    await page.route("**/api/basemap/style/*", (route) =>
      route.fulfill({ json: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#f2efe9" } }] } }),
    );
    await page.goto("/?v=temp_change&place=admin1%3AUS-TX&label=Texas");
    await expect(page.locator(".verdict h2")).toBeVisible();
    const map = page.locator("section[aria-label='Where inside the region']");
    await expect(map.getByText(/Zoom in to see streets, places and buildings/)).toBeVisible();
    await expect(map.getByRole("button", { name: "Show my location" })).toBeVisible();
    await expect(map.locator(".maplibregl-ctrl-scale")).toBeVisible();
    await expect(map.getByLabel("Colour strength")).toBeVisible();

    const outlines = await page.context().newPage();
    await outlines.route("**/api/basemap/**", (route) => route.abort());
    await outlines.goto("/?v=temp_change&place=admin1%3AUS-TX&label=Texas");
    await expect(outlines.locator(".verdict h2")).toBeVisible();
    const map2 = outlines.locator("section[aria-label='Where inside the region']");
    await expect(map2.locator(".maplibregl-ctrl-attrib")).toContainText("Natural Earth");
    await expect(map2.getByText(/Zoom in to see streets/)).toHaveCount(0);
  });
});

test.describe("ask page", () => {
  test.use({ serviceWorkers: "block" });
  test("the Ask button is ready before typing; an empty question gets a hint, not a request", async ({ page }) => {
    await page.route("**/api/ai/status", (route) => route.fulfill({ json: { enabled: true, provider: "test", model: null } }));
    let asked = 0;
    await page.route("**/api/ai/ask", (route) => { asked++; return route.abort(); });
    await page.goto("/ask");
    const ask = page.getByRole("button", { name: "Ask", exact: true });
    await expect(ask).toBeEnabled();
    await ask.click();
    await expect(page.locator("#q-need")).toHaveText("Type a question first (at least 3 characters).");
    await expect(page.getByRole("textbox", { name: "Your question" })).toBeFocused();
    await page.getByRole("textbox", { name: "Your question" }).fill("Is it warming?");
    await expect(page.locator("#q-need")).toHaveCount(0);
    expect(asked).toBe(0);
  });
});

test("detective cases: cards show measured findings; a case runs step by step to its summary", async ({ page }) => {
  await page.goto("/cases");
  const cards = page.locator(".case-card");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(16);
  // every card carries a finding computed from the data, not just a story
  await expect(cards.first().locator(".case-evidence")).toContainText("Measured");
  await page.getByRole("button", { name: /^Fire/ }).click();
  await expect(cards).toHaveCount(2);
  await page.getByRole("button", { name: /^All/ }).click();

  await page.getByRole("link", { name: /Lockdown 2020/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lockdown 2020: did the air really clear?");
  await expect(page.locator(".case-step")).toHaveCount(1);
  await expect(page.locator(".case-finding").first()).toContainText(/standard deviations below normal/);
  await expect(page.locator(".case-step").first().getByRole("img", { name: /values from/ })).toBeVisible();
  await page.getByRole("button", { name: /^Next step:/ }).click();
  await expect(page.locator(".case-step")).toHaveCount(2);
  await expect(page.getByRole("heading", { name: "Northern Italy, April 2020" })).toBeFocused();
  await page.getByRole("button", { name: /^Next step:/ }).click();
  await page.getByRole("button", { name: /^Next step:/ }).click();
  await page.getByRole("button", { name: "See the case summary" }).click();
  await expect(page.getByRole("heading", { name: "Case summary: what the measurements say" })).toBeFocused();
  await page.reload();
  await expect(page.locator(".case-step")).toHaveCount(1);
  await page.getByRole("button", { name: /^Next step:/ }).click();
  // showing the rest opens every step and the summary, and moves on to the first new step
  await page.getByRole("button", { name: "Show all steps" }).click();
  await expect(page.locator(".case-step")).toHaveCount(4);
  await expect(page.getByRole("heading", { name: "Delhi, April 2020" })).toBeFocused();
  await expect(page.getByRole("heading", { name: "Case summary: what the measurements say" })).toBeVisible();
  await expect(page.locator(".case-findings li")).toHaveCount(4);
  // the same analysis can be reopened on the Explore page
  const href = new URL((await page.getByRole("link", { name: "See the full record in Explore" }).first().getAttribute("href")) as string, "http://x");
  expect([href.pathname, href.searchParams.get("v"), href.searchParams.get("place")]).toEqual(["/", "no2", "preset:north_china_plain"]);
});

test("cell map of the whole Earth: merged blocks, full detail when zoomed in", async ({ page }) => {
  await page.goto("/?v=air_temp&place=preset%3Aglobe&label=Whole%20Earth");
  await expect(page.locator(".verdict h2")).toBeVisible({ timeout: 120000 });
  const map = page.locator("section[aria-label='Where inside the region']");
  const note = map.locator(".map-detail");
  await expect(note).toContainText("cells are merged into 2° blocks");
  await map.scrollIntoViewIfNeeded();
  const bb = (await map.locator(".map-box").boundingBox())!;
  await page.mouse.move(bb.x + bb.width * 0.52, bb.y + bb.height * 0.33);
  for (let i = 0; i < 5; i++) { await page.mouse.wheel(0, -300); await page.waitForTimeout(250); }
  await expect(note).toContainText("Full detail for the area in view", { timeout: 60000 });
  await expect(map).toContainText("the false-discovery control runs over the cells shown");
});
