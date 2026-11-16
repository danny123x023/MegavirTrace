#!/usr/bin/env node
// A 30-second demo video of MegavirTrace, rendered frame by frame from the running site.
//
//   FFMPEG=/path/to/ffmpeg AI_ANSWER=answer.ndjson node scripts/demo-video.mjs
//
// Environment: BASE (site, default the live one), OUT (output folder, default ../demo-video),
// AI_ANSWER (a saved /api/ai/ask/stream reply), FFMPEG (an ffmpeg with libx264).
//
// Every frame of the 30 fps video is a 1920 x 1080 screenshot (a 1440 x 810 page at 4/3 scale)
// taken after setting the pointer, the scroll position and the overlay for that frame's time,
// so the video is smooth and exactly 30 s however slowly the page renders (the map draws in
// software here). Waits for the network are simply not filmed. Captions, the pointer, click
// ripples, fades and the end card are drawn in the page. The Ask scene replays a real AI answer
// that passed the number check (saved once with curl), so retakes do not each cost an AI call.

import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE ?? "https://spacepiratesparadigm.com";
const OUT = path.resolve(process.env.OUT ?? "../demo-video");
const AI_ANSWER = process.env.AI_ANSWER ?? path.join(OUT, "ai-answer.ndjson");
const FFMPEG = process.env.FFMPEG ?? "ffmpeg";
const FPS = 30;
const TOTAL = 30;
const VIEW = { width: 1440, height: 810 };
const QUESTION = "Is Arctic sea ice really shrinking?";

// --------------------------------------------------------------------------------------------
// In-page overlay, driven by the video clock (no CSS transitions: frames are not real time)
// --------------------------------------------------------------------------------------------

function overlay() {
  const css = `
    #demo-cap { position: fixed; left: 50%; bottom: 30px; z-index: 2147483600; max-width: 84vw;
      padding: 13px 26px 14px; border-radius: 16px; background: rgba(15, 23, 42, 0.92); color: #fff;
      font-family: inherit; font-size: 23px; font-weight: 600; line-height: 1.35; letter-spacing: -0.01em;
      text-align: center; white-space: nowrap; box-shadow: 0 14px 44px rgba(15, 23, 42, 0.28);
      pointer-events: none; opacity: 0; transform: translate(-50%, 14px); }
    #demo-cap b { color: #a5b4fc; font-weight: 700; }
    #demo-fade { position: fixed; inset: 0; background: #fff; opacity: 0; z-index: 2147483610; pointer-events: none; }
    #demo-end { position: fixed; inset: 0; z-index: 2147483620; display: none; place-items: center;
      font-family: inherit; color: #0f172a;
      background: radial-gradient(900px 520px at 18% 12%, #e8eaff 0%, rgba(255,255,255,0) 70%),
                  radial-gradient(800px 480px at 85% 90%, #dff7ee 0%, rgba(255,255,255,0) 70%), #ffffff; }
    #demo-cursor { position: fixed; left: 0; top: 0; z-index: 2147483640; pointer-events: none;
      transform: translate(-200px, -200px); filter: drop-shadow(0 2px 3px rgba(0,0,0,0.25)); }
    .demo-ripple { position: fixed; width: 40px; height: 40px; margin: -20px 0 0 -20px; border-radius: 50%;
      border: 3px solid #6366f1; z-index: 2147483630; pointer-events: none; }
    html { scroll-behavior: auto !important; }
    .lp-live-dot { animation: none !important; }
    nextjs-portal { display: none !important; }`;
  const install = () => {
    if (!document.body || document.getElementById("demo-cap")) return;
    const st = document.createElement("style");
    st.textContent = css;
    document.head.appendChild(st);
    for (const id of ["demo-cap", "demo-fade", "demo-end"]) {
      const d = document.createElement("div");
      d.id = id;
      document.body.appendChild(d);
    }
    const cur = document.createElement("div");
    cur.id = "demo-cursor";
    cur.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M3 2 L3 19.5 L7.6 15.4 L10.6 22 L13.6 20.7 L10.7 14.2 L17 14.2 Z" fill="#fff" stroke="#111827" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cur);
  };
  window.__demoInstall = install;
  document.addEventListener("DOMContentLoaded", install);
  document.addEventListener(
    "mousemove",
    (e) => {
      const c = document.getElementById("demo-cursor");
      if (c) c.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 2}px)`;
    },
    true,
  );
  const clamp = (x) => Math.max(0, Math.min(1, x));
  const out = (p) => 1 - Math.pow(1 - p, 3);
  /** Draw the overlay for video time s.t: caption, fade, ripples, end card. */
  window.__demoApply = (s) => {
    install();
    const cap = document.getElementById("demo-cap");
    if (s.cap && s.cap.html) {
      if (cap.innerHTML !== s.cap.html) cap.innerHTML = s.cap.html;
      const p = out(clamp((s.t - s.cap.t0) / 0.35));
      cap.style.opacity = String(p);
      cap.style.transform = `translate(-50%, ${14 * (1 - p)}px)`;
    } else {
      cap.style.opacity = "0";
    }
    const f = s.fade;
    const fp = f ? clamp((s.t - f.t0) / f.dur) : 1;
    document.getElementById("demo-fade").style.opacity = String(f ? f.from + (f.to - f.from) * fp : 0);
    for (const r of document.querySelectorAll(".demo-ripple")) r.remove();
    for (const r of s.ripples) {
      const p = (s.t - r.t0) / 0.55;
      if (p < 0 || p >= 1) continue;
      const d = document.createElement("div");
      d.className = "demo-ripple";
      d.style.left = `${r.x}px`;
      d.style.top = `${r.y}px`;
      d.style.transform = `scale(${0.3 + 1.2 * out(p)})`;
      d.style.opacity = String(0.95 * (1 - p));
      document.body.appendChild(d);
    }
    const end = document.getElementById("demo-end");
    if (s.end) {
      if (!end.innerHTML) end.innerHTML = s.end.html;
      end.style.display = "grid";
      end.style.opacity = String(out(clamp((s.t - s.end.t0) / 0.45)));
    } else {
      end.style.display = "none";
    }
  };
}

const END_CARD = `
  <div style="text-align:center">
    <svg width="92" height="92" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
      <path d="M4 15 L9 11 L13 13 L20 7" fill="none" stroke="var(--series-2, #ea580c)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div style="font-size:68px;font-weight:800;letter-spacing:-0.035em;margin-top:10px">MegavirTrace</div>
    <div style="font-size:28px;color:#475569;margin-top:4px">Is this place <span style="color:var(--accent, #4f46e5);font-weight:700">really</span> changing?</div>
    <div style="margin-top:30px;display:inline-block;padding:12px 26px;border-radius:999px;background:var(--accent, #4f46e5);color:#fff;font-size:26px;font-weight:700;letter-spacing:-0.01em">spacepiratesparadigm.com</div>
    <div style="font-size:19px;color:#64748b;margin-top:26px">NASA Space Apps Challenge 2026 · Be an Earth System Trend Detective · Team Space Pirates Paradigm</div>
  </div>`;

// --------------------------------------------------------------------------------------------
// Frames on the video clock
// --------------------------------------------------------------------------------------------

const seqDir = path.join(OUT, "seq");
fs.rmSync(seqDir, { recursive: true, force: true });
fs.rmSync(path.join(OUT, "frames"), { recursive: true, force: true }); // from the screencast version
fs.mkdirSync(seqDir, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: VIEW,
  deviceScaleFactor: 4 / 3,
  colorScheme: "light",
  serviceWorkers: "block",
  locale: "en-GB",
});
await ctx.addInitScript(overlay);
const page = await ctx.newPage();
page.setDefaultTimeout(90_000);

let n = 0; // frames written
let posterFrame = 0;
let last = null;
const vt = () => n / FPS;
const state = { cap: null, fade: null, ripples: [], end: null };
const marks = [];
const mark = (name) => marks.push([name, vt()]);

async function frame() {
  await page.evaluate((s) => window.__demoApply(s), { ...state, t: vt() });
  const file = path.join(seqDir, `s${String(n).padStart(5, "0")}.jpg`);
  await page.screenshot({ path: file, type: "jpeg", quality: 92 });
  n++;
  last = file;
}
function animating() {
  const t = vt();
  return (
    (state.cap && t - state.cap.t0 < 0.4) ||
    (state.fade && t - state.fade.t0 < state.fade.dur + 0.05) ||
    state.ripples.some((r) => t - r.t0 < 0.6) ||
    (state.end && t - state.end.t0 < 0.5)
  );
}
/** Hold still for sec seconds: film every frame while something animates, else every second one. */
async function hold(sec) {
  const k = Math.round(sec * FPS);
  for (let i = 0; i < k; i++) {
    if (animating() || i % 2 === 0 || !last) await frame();
    else {
      fs.symlinkSync(last, path.join(seqDir, `s${String(n).padStart(5, "0")}.jpg`));
      n++;
    }
  }
}
/** Run step(p) for p in (0, 1] over sec seconds, one frame each. */
async function animate(sec, step) {
  const k = Math.max(1, Math.round(sec * FPS));
  for (let i = 1; i <= k; i++) {
    await step(i / k);
    await frame();
  }
}

const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
let mx = 1010;
let my = 560;
async function moveTo(x, y, sec = 0.7) {
  const [sx, sy] = [mx, my];
  await animate(sec, (p) => page.mouse.move(sx + (x - sx) * ease(p), sy + (y - sy) * ease(p)));
  [mx, my] = [x, y];
}
async function centre(loc, dx = 0, dy = 0) {
  const b = await loc.boundingBox();
  return [b.x + b.width / 2 + dx, b.y + b.height / 2 + dy];
}
function ripple(x, y) {
  state.ripples.push({ x, y, t0: vt() });
}
async function click(loc, sec = 0.7, dx = 0, dy = 0) {
  const [x, y] = await centre(loc, dx, dy);
  await moveTo(x, y, sec);
  ripple(x, y);
  await page.mouse.down();
  await page.mouse.up();
}
async function scrollTo(y, sec) {
  const s = await page.evaluate(() => window.scrollY);
  await animate(sec, (p) => page.evaluate((v) => window.scrollTo(0, v), s + (y - s) * ease(p)));
}
async function typeText(loc, text, framesPerChar) {
  for (const ch of text) {
    await loc.press(ch === " " ? "Space" : ch);
    for (let i = 0; i < framesPerChar; i++) await frame();
  }
}
const topOf = (loc) => loc.evaluate((e) => e.getBoundingClientRect().top + window.scrollY);
const caption = (html) => {
  state.cap = html ? { html, t0: vt() } : null;
};
const fadeTo = (from, to, dur) => {
  state.fade = { from, to, dur, t0: vt() };
};
/** Ready a freshly loaded page (not filmed): overlay in, pointer back in place. */
async function prep() {
  state.ripples = [];
  await page.evaluate(() => window.__demoInstall());
  await page.mouse.move(mx, my);
  await page.waitForTimeout(200);
}
const headline = (re) =>
  page.waitForFunction((src) => new RegExp(src).test(document.querySelector(".verdict h2")?.textContent ?? ""), re.source);

// --------------------------------------------------------------------------------------------
// The shots
// --------------------------------------------------------------------------------------------

// 1. Landing: the question, and the live result beside it
mark("landing");
await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
await page.locator(".lp-live-verdict").waitFor();
await page.waitForTimeout(1500);
await prep();
fadeTo(1, 0, 0.35);
caption("<b>MegavirTrace</b> · Is this place really changing? Honest answers from NASA data");
await hold(1.8);
await click(page.getByRole("link", { name: /Start exploring/ }).first(), 0.9);
await hold(0.3);

// 2. Explore: pick a place, read the verdict, switch the measurement
mark("explore");
await page.waitForURL(/\/explore/);
await page.locator(".verdict h2").waitFor();
await page.waitForTimeout(1200);
await prep();
caption("Pick <b>any place</b> on Earth: here, the Arctic");
const where = page.getByRole("combobox", { name: "Where" });
await click(where, 0.7);
await hold(0.1);
await typeText(where, "Arctic", 2);
const arctic = page.getByRole("option", { name: /^Arctic \(north of 66\.5°N\) ·/ });
await arctic.waitFor();
await page.waitForTimeout(300);
await hold(0.25);
await click(arctic, 0.45);
await hold(0.1);
await headline(/Surface temperature change in the Arctic/);
await page.waitForTimeout(1500); // map and chart drawn
caption("A verdict in plain words: <b>the Arctic is warming</b>");
await scrollTo(170, 0.6);
const h2 = page.locator(".verdict h2");
let [hx, hy] = await centre(h2, 120, 46);
await moveTo(hx, hy, 0.55);
await hold(1.45);
const what = page.getByLabel("What", { exact: true });
const [wx, wy] = await centre(what, 40, 0);
await moveTo(wx, wy, 0.6);
ripple(wx, wy);
await hold(0.2);
await what.selectOption("sea_ice");
await headline(/Sea ice concentration in the Arctic/);
await page.waitForTimeout(2000);
caption("Switch to any of <b>31 NASA measurements</b>: its sea ice is shrinking");
[hx, hy] = await centre(h2, 160, 46);
await moveTo(hx, hy, 0.6);
await hold(1.75);

// 3. Same page: where inside the region, and the trend with its range
mark("map-and-trend");
const mapSec = page.locator("section[aria-label='Where inside the region']");
caption("<b>Where</b> is it changing? Every cell tested, with false-discovery control");
await scrollTo((await topOf(mapSec)) - 84, 0.9);
const cb = await mapSec.locator("canvas").first().boundingBox();
const [zx, zy] = [cb.x + cb.width * 0.62, cb.y + cb.height * 0.15]; // the Barents and Kara seas
await moveTo(zx, zy, 0.6);
for (let i = 0; i < 8; i++) {
  await page.mouse.wheel(0, -100); // the map zooms in around the pointer
  await frame();
  await frame();
}
await page.waitForTimeout(1200); // tiles at the new zoom
await moveTo(zx + 4, zy + 3, 0.15); // the readout follows the pointer
posterFrame = n;
await hold(1.0);
const chart = page.getByRole("img", { name: /values from/ }).first();
caption("The trend and its 95% range: <b>two tests must agree</b>");
await scrollTo((await topOf(chart)) - 150, 0.9);
const chb = await chart.boundingBox();
await moveTo(chb.x + chb.width * 0.7, chb.y + chb.height * 0.55, 0.6);
await hold(1.15);
fadeTo(0, 1, 0.25);
await hold(0.27);

// 4. A detective case, step by step
mark("case");
await page.goto(`${BASE}/cases`, { waitUntil: "domcontentloaded" });
await page.locator(".case-card").first().waitFor();
await page.waitForTimeout(800);
await prep();
fadeTo(1, 0, 0.3);
caption("<b>20 detective cases</b>: real events, investigated with NASA data");
await hold(0.45);
await click(page.getByRole("link", { name: /Europe.s 2003 heatwave/ }), 0.8);
await hold(0.15);
await page.waitForURL(/europe-heatwave-2003/);
await page.locator(".case-step").first().waitFor();
await page.waitForTimeout(1200);
await prep();
await hold(0.5);
await scrollTo((await topOf(page.locator(".case-step").first())) - 84, 0.9);
const finding = page.locator(".case-finding").first();
[hx, hy] = await centre(finding, 260, 12);
await moveTo(hx, hy, 0.6);
await hold(1.45);
fadeTo(0, 1, 0.25);
await hold(0.27);

// 5. Ask the AI scientist: a real answer that passed the number check
mark("ask");
const answer = fs.readFileSync(AI_ANSWER, "utf8");
await page.route("**/api/ai/ask/stream", (r) =>
  r.fulfill({ status: 200, contentType: "application/x-ndjson", body: answer }),
);
await page.goto(`${BASE}/ask`, { waitUntil: "domcontentloaded" });
const box = page.getByRole("textbox", { name: "Your question" });
await box.waitFor();
await page.waitForTimeout(800);
await prep();
fadeTo(1, 0, 0.3);
caption("Ask the <b>AI scientist</b>: it never computes, and <b>every number is checked</b>");
await click(box, 0.55);
await hold(0.1);
await typeText(box, QUESTION, 1);
await click(page.getByRole("button", { name: "Ask", exact: true }), 0.4);
await hold(0.1);
const check = page.getByText(/Number check passed/);
await check.waitFor();
await page.waitForTimeout(400);
await scrollTo((await topOf(page.getByText(/You asked:/).first())) - 110, 0.7);
[hx, hy] = await centre(check, 40, 4);
await moveTo(hx, hy, 0.5);
await hold(1.4);

// 6. End card, filling the video to exactly TOTAL seconds
mark("end");
const left = TOTAL - vt();
if (left < 1.2) throw new Error(`the shots run ${vt().toFixed(2)} s: no room for the end card`);
caption(null);
state.end = { html: END_CARD, t0: vt() };
await page.mouse.move(VIEW.width - 2, VIEW.height - 2);
await page.evaluate(() => (document.getElementById("demo-cursor").style.display = "none"));
await hold(left);
await browser.close();

marks.push(["(end)", vt()]);
for (let i = 0; i + 1 < marks.length; i++) {
  console.log(`${marks[i][0].padEnd(14)} ${marks[i][1].toFixed(2).padStart(6)} s  ${(marks[i + 1][1] - marks[i][1]).toFixed(2)} s`);
}

// --------------------------------------------------------------------------------------------
// H.264, 30 fps
// --------------------------------------------------------------------------------------------

const mp4 = path.join(OUT, `megavirtrace-demo-${TOTAL}s.mp4`);
execFileSync(
  FFMPEG,
  ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", path.join(seqDir, "s%05d.jpg"),
   "-frames:v", String(TOTAL * FPS),
   "-vf", "scale=in_range=pc:out_range=tv:in_color_matrix=bt601:out_color_matrix=bt709,format=yuv420p",
   "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-color_range", "tv", "-colorspace", "bt709",
   "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", mp4],
  { stdio: "inherit" },
);
fs.copyFileSync(path.join(seqDir, `s${String(posterFrame + 10).padStart(5, "0")}.jpg`), path.join(OUT, "poster.jpg"));
console.log(`wrote ${mp4}: ${n} frames, ${(fs.statSync(mp4).size / 1e6).toFixed(1)} MB`);
