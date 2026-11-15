import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = ["/", "/explore", "/compare", "/related", "/start", "/cases", "/cases/europe-heatwave-2003", "/ask", "/methods", "/imports", "/admin"];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });
    for (const path of PAGES) {
      test(`no serious or critical accessibility violations on ${path}`, async ({ page }) => {
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        await page.goto(path);
        if (path === "/") await expect(page.locator(".lp-live-verdict")).toBeVisible();
        else if (path === "/explore" || path === "/compare" || path === "/related") await expect(page.locator(".verdict h2").first()).toBeVisible();
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
  await page.goto("/explore");
  await expect(page.locator(".verdict h2")).toContainText(/per decade|no clear trend|mixed/);
  await expect(page.getByRole("img", { name: /values from/ })).toBeVisible();
  // the chart / table switch: two icon buttons, the view shown is pressed
  const toTable = page.getByRole("button", { name: "Show table" }).first();
  const toChart = page.getByRole("button", { name: "Show chart" }).first();
  await expect(toChart).toHaveAttribute("aria-pressed", "true");
  await expect(toTable).toHaveAttribute("aria-pressed", "false");
  await toTable.click();
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(toTable).toHaveAttribute("aria-pressed", "true");
  await toChart.click();
  await expect(page.getByRole("img", { name: /values from/ })).toBeVisible();
  await toTable.click();
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "CSV" })).toHaveAttribute("href", /export\?format=csv/);
  const nb = await page.request.get(await page.getByRole("link", { name: /Notebook/ }).getAttribute("href") as string);
  expect(nb.ok()).toBeTruthy();
});

test("landing page: what the site is, a live result from the data, and the way in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Is this place really changing?");
  const live = page.locator(".lp-live");
  await expect(live.locator(".lp-live-verdict")).toContainText(/per decade/);
  await expect(live).toContainText("GISTEMP");
  await expect(page.getByRole("img", { name: /one stripe per year from 1880/ })).toBeVisible();
  await expect(page.locator(".lp-stat")).toHaveCount(4);
  for (const name of ["Explore", "Compare", "Related variables", "Detective cases", "Ask the AI", "Start here"]) {
    await expect(page.locator(".lp-features").getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(page.locator(".lp-case")).toHaveCount(3);
  await expect(page.locator(".lp-products li")).not.toHaveCount(0);
  await page.getByRole("link", { name: "Start exploring" }).first().click();
  await expect(page).toHaveURL(/\/explore/);
  await expect(page.locator(".verdict h2")).toBeVisible();
});

test("old Explore links (/?v=...) open Explore with the same settings", async ({ page }) => {
  await page.goto("/?v=temp_change&place=admin1%3AUS-TX&label=Texas");
  await expect(page).toHaveURL(/\/explore\?.*v=temp_change/);
  await expect(page.locator(".verdict h2")).toContainText("Texas");
});

test("the site has a favicon (tab icon) and a home-screen icon", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator('head link[rel="icon"]').first()).toHaveAttribute("href", /icon|favicon/);
  for (const path of ["/favicon.ico", "/icon.svg", "/apple-icon.png"]) {
    const r = await request.get(path);
    expect(r.status(), path).toBe(200);
    expect(r.headers()["content-type"], path).toMatch(/^image\//);
  }
});

test("new measurements (2026-11-15): listed by theme; a short record opens on monthly values", async ({ page }) => {
  await page.goto("/explore");
  await expect(page.locator(".verdict h2")).toBeVisible();
  const what = page.getByLabel("What");
  await expect(what.locator('optgroup[label="Sky and air"] option')).toHaveText(["Cloud cover", "Sunshine at the ground", "Wind speed near the ground", "Ozone layer (total ozone)"]);
  for (const name of ["Sea surface salinity", "Ocean chlorophyll (phytoplankton)", "Long-record rainfall", "Water vapour in the air", "Snow water (snowpack)"]) {
    await expect(what.locator("option", { hasText: name })).toHaveCount(1);
  }
  // sea salinity is measured from space only since 2015: it opens on the monthly chart, and the test
  // uses yearly means, so a short, persistent record is honestly reported as not testable
  await page.goto("/explore?v=sea_salinity&place=preset%3Abay_of_bengal&label=Bay+of+Bengal");
  await expect(page.locator(".verdict h2")).toContainText("Sea surface salinity in the Bay of Bengal");
  await expect(page).toHaveURL(/mode=monthly/);
  // the note says the baseline is the years selected (it moves when the years change)
  await expect(page.getByText("The chart shows each month against its usual value over the years selected")).toBeVisible();
});

test("explore: search a place and switch modes", async ({ page }) => {
  await page.goto("/explore");
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
  await page.goto("/explore");
  const href = await page.getByRole("link", { name: "Embeddable card" }).getAttribute("href");
  await page.goto(href as string);
  await expect(page.locator(".embed-card h1")).toBeVisible();
  await expect(page.locator(".embed-card a[href*='/explore?v=']").first()).toBeVisible();
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
  await page.goto("/explore");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("¿De verdad está cambiando este lugar?");
  await expect(page.locator(".verdict h2")).toContainText(/por década|sin tendencia clara|evidencia es mixta/i);
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
});

test("works offline after one visit (production build)", async ({ page, context }) => {
  await page.goto("/explore?v=temp_change&place=admin1%3AUS-TX&label=Texas");
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

test("phone layout: nothing wider than the screen; a short header whose menu shows every page link", async ({ browser }) => {
  for (const width of [320, 360, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 844 } });
    await page.goto("/explore");
    await expect(page.locator(".verdict h2")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.goto("/");
    await expect(page.locator(".lp-live-verdict")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    // one short row: brand, language and the menu button, each a 44 px touch target
    const header = page.locator(".site-header");
    expect((await header.boundingBox())!.height).toBeLessThan(80);
    const links = page.getByRole("navigation", { name: "Main" }).getByRole("link");
    await expect(links.first()).toBeHidden();
    const menu = page.getByRole("button", { name: "Menu" });
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    expect((await menu.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect(links).toHaveCount(8);
    for (const link of await links.all()) {
      await expect(link).toBeInViewport({ ratio: 1 });
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    // the theme switch sits in the menu with a visible word and its full name
    await expect(page.getByRole("button", { name: "Dark mode" })).toContainText("Dark");
    // Escape closes the menu; following a link closes it too
    await page.keyboard.press("Escape");
    await expect(links.first()).toBeHidden();
    await menu.click();
    await links.filter({ hasText: "Method" }).click();
    await expect(page).toHaveURL(/\/methods$/);
    await expect(links.first()).toBeHidden();
    // nothing on the page is set smaller than 12 px
    const tiny = await page.evaluate(() =>
      [...document.querySelectorAll("body *")].filter((e) => (e as HTMLElement).offsetParent && [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim()) && parseFloat(getComputedStyle(e).fontSize) < 12).length,
    );
    expect(tiny).toBe(0);
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
  await expect(sources).toHaveCount(23);
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
  await expect(page.getByRole("link", { name: /Manage the account and check every source in the Admin panel/ })).toHaveAttribute("href", "/admin#earthdata");
});


test("every result card can go full screen and back", async ({ page }) => {
  await page.goto("/explore");
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

test("map readout: the coordinates and the cell under the pointer", async ({ page }) => {
  await page.goto("/explore?v=temp_change&place=admin1%3AUS-TX&label=Texas");
  await expect(page.locator(".verdict h2")).toContainText("Texas");
  const map = page.locator("section[aria-label='Where inside the region']");
  await expect(map).toContainText("pass the false-discovery test"); // the cells are drawn
  await map.locator(".map-box").scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  const box = (await map.locator(".map-box").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const readout = map.locator(".map-readout");
  await expect(readout).toContainText(/\d+\.\d+° N, \d+\.\d+° W/); // Texas: north, west
  await expect(readout).toContainText(/per decade/);
  await expect(readout).toContainText(/false-discovery test/);
  await expect(readout).toContainText(/cell of [\d.]+° around/);
  await page.mouse.move(box.x + box.width / 2, box.y - 40); // off the map
  await expect(readout).toHaveCount(0);
});

test("map readout on a phone: a tap shows what is there", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, serviceWorkers: "block" });
  const page = await ctx.newPage();
  await page.goto("/explore?v=temp_change&place=admin1%3AUS-TX&label=Texas");
  const map = page.locator("section[aria-label='Where inside the region']");
  await expect(map).toContainText("pass the false-discovery test");
  await map.locator(".map-box").scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  const box = (await map.locator(".map-box").boundingBox())!;
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  await expect(map.locator(".map-readout")).toContainText(/° N, .*° W/);
  await expect(map.locator(".map-readout")).toContainText(/per decade/);
  await ctx.close();
});

test.describe("AI explanation card", () => {
  test.use({ serviceWorkers: "block" });
  test("the Explain button and the full-screen button sit side by side, never on top of each other", async ({ page }) => {
    await page.route("**/api/ai/status", (route) => route.fulfill({ json: { enabled: true, provider: "zai", model: "test" } }));
    await page.goto("/explore");
    const card = page.locator("section[aria-label='AI explanation']");
    const explain = card.getByRole("button", { name: "Explain" });
    await expect(explain).toBeVisible();
    const fs = card.getByRole("button", { name: "Show full screen" });
    await expect(fs).toHaveCount(1);
    const [a, b] = [(await explain.boundingBox())!, (await fs.boundingBox())!];
    const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
    expect(apart).toBe(true);
  });
});

test.describe("map base layers", () => {
  // the service worker would answer the map requests itself, out of reach of page.route
  test.use({ serviceWorkers: "block" });
  test("map: street map with location and scale; country outlines when it cannot load", async ({ page }) => {
    // a stand-in street-map style (the real one is relayed from OpenStreetMap tiles by the API)
    await page.route("**/api/basemap/style/*", (route) =>
      route.fulfill({ json: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#f2efe9" } }] } }),
    );
    await page.goto("/explore?v=temp_change&place=admin1%3AUS-TX&label=Texas");
    await expect(page.locator(".verdict h2")).toBeVisible();
    const map = page.locator("section[aria-label='Where inside the region']");
    await expect(map.getByText(/Zoom in to see streets, places and buildings/)).toBeVisible();
    await expect(map.getByRole("button", { name: "Show my location" })).toBeVisible();
    await expect(map.locator(".maplibregl-ctrl-scale")).toBeVisible();
    await expect(map.getByLabel("Colour strength")).toBeVisible();

    const outlines = await page.context().newPage();
    await outlines.route("**/api/basemap/**", (route) => route.abort());
    await outlines.goto("/explore?v=temp_change&place=admin1%3AUS-TX&label=Texas");
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
    await page.route(/\/api\/ai\/ask(\/stream)?$/, (route) => { asked++; return route.abort(); });
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

  test("progress lines show while the AI works, then the checked answer", async ({ page }) => {
    await page.route("**/api/ai/status", (route) => route.fulfill({ json: { enabled: true, provider: "test", model: "m" } }));
    const lines = [
      { type: "progress", step: "thinking", round: 1 },
      { type: "progress", step: "tool", tool: "run_trend_analysis", variable: "Rainfall", places: ["Sahel"], query: null },
      { type: "progress", step: "thinking", round: 2 },
      { type: "progress", step: "check" },
      { type: "result", result: { mode: "answered", answer: { headline: "Rainfall in the Sahel is rising.", explanation: "A short answer.", follow_up_questions: [] }, check: { numbers_checked: 3 }, analyses: [], timing: { total_s: 9.5, ai_calls: 2 } } },
    ];
    await page.route("**/api/ai/ask/stream", (route) => route.fulfill({ contentType: "application/x-ndjson", body: lines.map((l) => JSON.stringify(l)).join("\n") + "\n" }));
    await page.goto("/ask");
    await page.getByRole("textbox", { name: "Your question" }).fill("Is rainfall in the Sahel changing?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Rainfall in the Sahel is rising." })).toBeVisible();
    await expect(page.getByText("Answered in 9.5 s")).toBeVisible();
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
  expect([href.pathname, href.searchParams.get("v"), href.searchParams.get("place")]).toEqual(["/explore", "no2", "preset:north_china_plain"]);
});

test("cell map of the whole Earth: merged blocks, full detail when zoomed in", async ({ page }) => {
  await page.goto("/explore?v=air_temp&place=preset%3Aglobe&label=Whole%20Earth");
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

test.describe("admin panel", () => {
  // a throwaway token (local test servers: screenshot-only-token; CI: MEGAVIR_E2E_ADMIN_TOKEN)
  const TOKEN = process.env.MEGAVIR_E2E_ADMIN_TOKEN ?? "screenshot-only-token";
  test.use({ serviceWorkers: "block" });

  test("sign in with a session, choose the AI service, see the sessions, sign out", async ({ page }) => {
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Administrator sign-in" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "AI service" })).toHaveCount(0); // nothing to manage before signing in
    await page.getByLabel("Administrator token").fill("not-the-token");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("That token is not right.")).toBeVisible();
    await page.getByLabel("Administrator token").fill(TOKEN);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "AI service" })).toBeVisible();
    // the browser keeps a session, never the token
    const stored = await page.evaluate(() => [sessionStorage.getItem("mt-admin-session"), JSON.stringify({ ...localStorage, ...sessionStorage })]);
    expect(stored[0]).toBeTruthy();
    expect(stored[1]).not.toContain(TOKEN);
    for (const name of ["Claude (Anthropic)", "Z.ai (GLM)"]) await expect(page.getByRole("heading", { name, level: 3 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "NASA Earthdata account" })).toBeVisible();
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    // models are picked from a list (any other name can be typed after "Other model…")
    const claudeModel = page.getByRole("combobox", { name: "Model" }).first();
    await expect(claudeModel.locator("option")).toContainText(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]);
    const before = await claudeModel.inputValue();
    const pick = before === "claude-sonnet-5-5" ? "claude-haiku-5-5" : "claude-sonnet-5-5";
    await claudeModel.selectOption(pick);
    await page.getByRole("button", { name: "Save model" }).first().click();
    await expect(page.getByText("Model saved.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Claude (Anthropic)", level: 3 }).locator("xpath=..")
      .getByRole("combobox", { name: "Model" })).toHaveValue(pick);
    await claudeModel.selectOption({ label: "Other model…" });
    await expect(page.getByLabel("Model name")).toBeVisible();
    await claudeModel.selectOption(pick);
    await expect(page.getByLabel("Model name")).toHaveCount(0);
    // switching the AI off is immediate (the test servers keep their own settings file)
    await page.getByRole("button", { name: /^Off/ }).click();
    await expect(page.getByRole("button", { name: /^Off/ })).toHaveAttribute("aria-pressed", "true");
    expect((await (await page.request.get("/api/ai/status")).json()).enabled).toBe(false);
    // the session is listed as this browser; signing out ends it on the server
    const sessions = page.locator("#sess-h").locator("xpath=ancestor::section");
    await expect(sessions.getByRole("row", { name: /this browser/ })).toBeVisible();
    const secret = stored[0] as string;
    await sessions.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Administrator sign-in" })).toBeVisible();
    const after = await page.request.get("/api/admin/overview", { headers: { "X-Admin-Session": secret } });
    expect((await after.json()).role).toBeNull();
  });
});
