"use client";

import Link from "next/link";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import Sparkline from "@/components/Sparkline";
import { apiGet, type CaseSummary, type Variable } from "@/lib/api";
import { fmtSigned } from "@/lib/format";
import { GITHUB_URL, GitHubIcon } from "@/components/GitHub";
import { changeUnit, type Lang, THEME_ES, useI18n, varText } from "@/lib/i18n";
import { DIVERGING } from "@/lib/palette";

// The landing page: what MegavirTrace is, in one screen, then what you can do, how a verdict is
// made, real cases and the data behind it.  Every number on it comes from the API (GET /landing,
// GET /cases); the words around them are fixed.

type Hero = {
  analysis_id: string; variable: Variable; region: string; units: string;
  labels: string[]; values: (number | null)[]; trend_line: (number | null)[];
  headline: string; per_decade: number; significant: boolean; product: string; doi: string | null; last_month: string;
  since: number; full_since: number; full_per_decade: number;  // headline rate since `since`; the long-run average as context
};
type Summary = {
  variables: number; themes: string[]; products: string[]; first_month: string | null; last_month: string | null;
  cases: number; hero: Hero | null;
};

const FEATURED = ["europe-heatwave-2003", "arctic-sea-ice-2012", "lockdown-air-2020"];
const HERO_EXPLORE = "/explore?v=temp_change&mode=annual&place=preset%3Aglobe&label=Whole+Earth";
const heroExplore = (since: number) => `${HERO_EXPLORE}&start=${since}`;  // the same analysis as the headline

const TRY = [
  { label: "The whole Earth's temperature", href: HERO_EXPLORE },
  { label: "Arctic air", href: "/explore?v=air_temp&place=preset%3Aarctic&label=Arctic+%28north+of+66.5%C2%B0N%29" },
  { label: "Sea level", href: "/explore?v=sea_level&place=preset%3Aglobe&label=Whole+Earth" },
  { label: "Siberia's ground", href: "/explore?v=ground_temp&place=preset%3Asiberia&label=Siberia" },
];

const isNum = (v: number | null | undefined): v is number => v !== null && v !== undefined && Number.isFinite(v);

function Icon({ d, size = 20 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

const ICONS = {
  explore: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM21 21l-4.35-4.35M7.5 13l2.2-2.4 1.9 1.6 3-3.4",
  compare: "M9 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM15 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z",
  related: "M3 9c2-3 4-3 6 0s4 3 6 0 4-3 6 0M3 15.5c2-3 4-3 6 0s4 3 6 0 4-3 6 0",
  cases: "M13.5 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21H11M13.5 3 19 8.5v1.5M13.5 3v5.5H19M16.5 13a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM21 21.5l-2-2",
  ask: "M20.5 11.5a8 8 0 0 1-11.7 7.1L4 19.8l1.2-4.4A8 8 0 1 1 20.5 11.5ZM8.5 11.5h.01M12.5 11.5h.01M16.5 11.5h.01",
  start: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM15.6 8.4l-2.1 5.1-5.1 2.1 2.1-5.1 5.1-2.1Z",
  check: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM8 12.2l2.7 2.7L16.2 9",
  arrow: "M5 12h14M13 6l6 6-6 6",
};

function Orbit() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <ellipse cx="12" cy="12" rx="10.5" ry="4" transform="rotate(-24 12 12)" strokeWidth="1.6" />
    </svg>
  );
}

// "2026, to October" when the last year is not complete
function yearLabel(label: string, lastMonth: string | undefined, lang: Lang, t: (s: string, v?: Record<string, string | number>) => string) {
  if (!lastMonth || !lastMonth.startsWith(label) || lastMonth.endsWith("-12")) return label;
  const month = new Date(Date.UTC(2000, Number(lastMonth.slice(5, 7)) - 1, 1)).toLocaleString(lang, { month: "long", timeZone: "UTC" });
  return t("{year}, to {month}", { year: label, month });
}

// Stripes read like a picture: deep blue (coldest) to deep red (warmest) in both themes, blended
// between the palette's matched steps, with the same °C per step on both sides of the average.
const STRIPE_RAMP = [...[...DIVERGING.light.negative].reverse(), DIVERGING.light.mid, ...DIVERGING.light.positive];
const rgb = (h: string) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
function stripeColor(v: number, lim: number): string {
  const x = Math.max(-1, Math.min(1, v / lim)) * 4 + 4; // 0..8 along the ramp
  const i = Math.min(7, Math.floor(x)), f = x - i;
  const a = rgb(STRIPE_RAMP[i]), b = rgb(STRIPE_RAMP[i + 1]);
  return `rgb(${a.map((c, k) => Math.round(c + (b[k] - c) * f)).join(",")})`;
}

// Sections below the first screen rise into view once.  Nothing is hidden without JavaScript, with
// reduced motion, or if it is already on screen when the page opens.
function useReveal(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current;
    if (!el || !("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const items = [...el.querySelectorAll<HTMLElement>(".lp-reveal")].filter((x) => x.getBoundingClientRect().top > window.innerHeight * 0.9);
    items.forEach((x) => x.classList.add("lp-hidden"));
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.remove("lp-hidden"); io.unobserve(e.target); }
    }, { rootMargin: "0px 0px -6% 0px" });
    items.forEach((x) => io.observe(x));
    return () => { io.disconnect(); items.forEach((x) => x.classList.remove("lp-hidden")); };
  }, [root]);
}

function CountUp({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(value);
  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const step = (now: number) => {
        const k = Math.min(1, (now - t0) / 1100);
        setShown(Math.round(value * (1 - (1 - k) ** 3)));
        if (k < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, { threshold: 0.5 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [value]);
  return <span ref={ref}>{shown}</span>;
}

// ---- the live result in the first screen -------------------------------------------------------

function LiveChart({ hero }: { hero: Hero }) {
  const { lang, t } = useI18n();
  const vals = hero.values;
  const n = vals.length;
  const all = [...vals, ...hero.trend_line].filter(isNum);
  const lo0 = Math.min(0, ...all), hi0 = Math.max(0, ...all);
  const span = hi0 - lo0 || 1;
  const lo = lo0 - span * 0.1, hi = hi0 + span * 0.32; // room above the curve for the latest value
  const W = 600, H = 220;
  const X = (i: number) => (i / Math.max(1, n - 1)) * W;
  const Y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  let line = "", area = "", pen = false, first = -1, lastI = -1;
  vals.forEach((v, i) => {
    if (!isNum(v)) { pen = false; return; }
    line += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
    if (first < 0) first = i;
    lastI = i;
    pen = true;
  });
  if (first >= 0) area = `${line}L${X(lastI).toFixed(1)},${H}L${X(first).toFixed(1)},${H}Z`;
  const trend = hero.trend_line.map((v, i) => (isNum(v) ? `${X(i).toFixed(1)},${Y(v).toFixed(1)}` : null)).filter(Boolean);
  const last = lastI >= 0 ? (vals[lastI] as number) : null;
  const zeroTop = (Y(0) / H) * 100;
  return (
    <div className="lp-chart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="lp-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--series-2)" stopOpacity="0.32" />
            <stop offset="1" stopColor="var(--series-2)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <line x1="0" x2={W} y1={Y(0)} y2={Y(0)} stroke="var(--axis)" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        <path d={area} fill="url(#lp-area)" />
        <path d={line} fill="none" stroke="var(--series-2)" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {trend.length > 1 && <polyline points={trend.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray="6 5" vectorEffect="non-scaling-stroke" />}
      </svg>
      <span className="lp-chart-zero" style={{ top: `${zeroTop}%` }}>{t("1951–1980 average")}</span>
      {last !== null && (
        <span className="lp-chart-end" style={{ left: `${(X(lastI) / W) * 100}%`, top: `${(Y(last) / H) * 100}%` }}>
          <span className="lp-chart-value">{fmtSigned(last, 2)} {hero.units}</span>
        </span>
      )}
      <div className="lp-chart-years">
        <span>{hero.labels[first] ?? ""}</span>
        <span>{lastI >= 0 ? yearLabel(hero.labels[lastI], hero.last_month, lang, t) : ""}</span>
      </div>
    </div>
  );
}

function LiveCard({ summary, failed }: { summary: Summary | null; failed: boolean }) {
  const { lang, t } = useI18n();
  const hero = summary?.hero;
  if (!hero) {
    return (
      <div className="lp-live card" aria-busy={!failed}>
        <div className="lp-live-top"><span className="lp-live-dot" />{t("Live result")}</div>
        {failed || summary ? (
          <p className="muted small">{t("The live result could not be loaded just now. Everything else on the site still works.")}</p>
        ) : (
          <>
            <div className="lp-skel lp-skel-title" />
            <div className="lp-skel lp-skel-chart" />
            <div className="lp-skel lp-skel-line" />
            <span className="visually-hidden" role="status">{t("Computing the live result…")}</span>
          </>
        )}
      </div>
    );
  }
  const name = varText(hero.variable, lang);
  const title = `${name} · ${hero.region}`;
  return (
    <figure className="lp-live card">
      <div className="lp-live-top">
        <span className="lp-live-dot" />
        <span>{t("Live result")}</span>
        <span className="lp-live-src">{t("computed from {product}", { product: hero.product })}</span>
      </div>
      <figcaption className="lp-live-title">{title.charAt(0).toUpperCase() + title.slice(1)}</figcaption>
      <LiveChart hero={hero} />
      <p className="lp-live-verdict">{hero.headline}</p>
      <div className="lp-live-badges">
        <span className={`lp-badge ${hero.significant ? "lp-badge-yes" : ""}`}>
          {hero.significant && <Icon d={ICONS.check} size={14} />}
          {hero.significant ? t("More than chance") : t("Not clearly more than chance")}
        </span>
        <span className="lp-badge">{t("Trend since {year}: {x} per decade", { year: String(hero.since), x: `${fmtSigned(hero.per_decade, 2)} ${changeUnit(hero.units, lang)}` })}</span>
        <span className="lp-badge">{t("Average since {year}: {x} per decade", { year: String(hero.full_since), x: `${fmtSigned(hero.full_per_decade, 2)} ${changeUnit(hero.units, lang)}` })}</span>
      </div>
      <Link className="lp-live-link" href={heroExplore(hero.since)}>
        {t("Open this result in Explore")} <Icon d={ICONS.arrow} size={15} />
      </Link>
    </figure>
  );
}

// ---- one stripe per year --------------------------------------------------------------------------

function Stripes({ hero }: { hero: Hero }) {
  const { lang, t } = useI18n();
  const [at, setAt] = useState<number | null>(null);
  const vals = hero.values;
  const finite = vals.filter(isNum);
  if (finite.length < 10) return null;
  const lim = Math.max(...finite.map(Math.abs)) || 1;
  const color = (v: number | null) => (isNum(v) ? stripeColor(v, lim) : "transparent");
  const i0 = vals.findIndex(isNum);
  const i1 = vals.length - 1 - [...vals].reverse().findIndex(isNum);
  const firstY = hero.labels[i0], lastY = hero.labels[i1];
  const label = t("Surface temperature of the whole Earth, one stripe per year from {first} to {last}: from {min} to {max} {units} against the 1951–1980 average.", {
    first: firstY, last: lastY, min: fmtSigned(Math.min(...finite), 2), max: fmtSigned(Math.max(...finite), 2), units: hero.units,
  });
  const n = vals.length;
  return (
    <figure className="lp-stripes lp-reveal">
      <div
        className="lp-stripes-band" role="img" aria-label={label}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const i = Math.floor(((e.clientX - r.left) / r.width) * n);
          setAt(i >= 0 && i < n && isNum(vals[i]) ? i : null);
        }}
        onMouseLeave={() => setAt(null)}
      >
        <svg viewBox={`0 0 ${n} 1`} preserveAspectRatio="none" aria-hidden="true">
          {vals.map((v, i) => <rect key={i} x={i} y={0} width={1.04} height={1} fill={color(v)} />)}
        </svg>
        {at !== null && (
          <span className="lp-stripes-tip" style={{ left: `clamp(64px, ${((at + 0.5) / n) * 100}%, calc(100% - 64px))` }} aria-hidden="true">
            <strong>{yearLabel(hero.labels[at], hero.last_month, lang, t)}</strong> {fmtSigned(vals[at], 2)} {hero.units}
          </span>
        )}
      </div>
      <div className="lp-stripes-years" aria-hidden="true"><span>{firstY}</span><span>{lastY}</span></div>
      <figcaption className="small muted">
        {t("Every stripe is one year of the whole Earth's surface temperature, {first}–{last}: blue is cooler and red is warmer than the 1951–1980 average. Point at a stripe to see its year.", { first: firstY, last: lastY })}
        {" "}<span className="nowrap">{t("Data")}: {hero.product}</span>
      </figcaption>
    </figure>
  );
}

// ---- page -----------------------------------------------------------------------------------------

function Section({ id, eyebrow, title, children, className = "" }: { id: string; eyebrow: string; title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`lp-section lp-reveal ${className}`} aria-labelledby={id}>
      <p className="lp-eyebrow">{eyebrow}</p>
      <h2 id={id} className="lp-h2">{title}</h2>
      {children}
    </section>
  );
}

export default function Landing() {
  const { lang, t } = useI18n();
  const root = useRef<HTMLDivElement>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [failed, setFailed] = useState(false);
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  useReveal(root);

  useEffect(() => {
    let gone = false;
    setFailed(false);
    apiGet<Summary>("/landing", { lang }).then((s) => { if (!gone) setSummary(s); }).catch(() => { if (!gone) setFailed(true); });
    apiGet<{ cases: CaseSummary[] }>("/cases", { lang })
      .then((r) => { if (!gone) setCases(FEATURED.map((id) => r.cases.find((c) => c.id === id)).filter((c): c is CaseSummary => !!c)); })
      .catch(() => { if (!gone) setCases([]); });
    return () => { gone = true; };
  }, [lang]);

  const nVars = summary?.variables ?? 31; // until the numbers arrive
  const nCases = summary?.cases ?? 20;
  const theme = (th: string) => (lang === "es" ? THEME_ES[th] ?? th : th);

  const features = [
    { href: "/explore", icon: ICONS.explore, tone: "blue", title: t("Explore"), text: t("Pick any city, country, state or ocean and one of {n} measurements: get a verdict in plain words, the trend per decade and a map of where it changes.", { n: nVars }) },
    { href: "/compare", icon: ICONS.compare, tone: "orange", title: t("Compare"), text: t("Put two places side by side and test whether their trends really differ, not just whether they look different.") },
    { href: "/related", icon: ICONS.related, tone: "green", title: t("Related variables"), text: t("Find measurements that move together, even months apart, with a clear reminder that a link is not a cause.") },
    { href: "/cases", icon: ICONS.cases, tone: "indigo", title: t("Detective cases"), text: t("{n} real events and long-term changes, from Europe's 2003 heatwave to India's groundwater, investigated step by step with the data.", { n: nCases }) },
    { href: "/ask", icon: ICONS.ask, tone: "pink", title: t("Ask the AI"), text: t("Ask in your own words. The AI runs the analyses and explains them; every number it writes is checked against the results.") },
    { href: "/start", icon: ICONS.start, tone: "teal", title: t("Start here"), text: t("New to this? Say what kind of place you care about and get the measurements worth a look.") },
  ];

  const steps = [
    { title: t("Choose a place and a measurement"), text: t("A country, state, city, ocean region, or a box you draw on the map.") },
    { title: t("Average the NASA data over it"), text: t("Month by month, weighted by the area of each grid cell, then turned into yearly or seasonal values.") },
    { title: t("Test the trend against chance"), text: t("Two tests must agree at α = 0.05, allowing for memory from one year to the next; maps add a false-discovery control.") },
    { title: t("Read it, check it, take it away"), text: t("A verdict in plain words, the chart and the map, and every number as CSV, a notebook or a card for your own site.") },
  ];

  const promises = [
    t("Computed from NASA data, never typed in: each number links back to its data product."),
    t("Checked on thousands of simulated records: false alarms stay close to the 5% the tests promise."),
    t("The verdict comes from fixed templates; the optional AI only explains, and its numbers are checked."),
    t("Open: download every series, read the code (Apache 2.0), and use it offline in English or Spanish."),
  ];

  return (
    <div className="landing" ref={root}>
      <section className="lp-hero" aria-labelledby="lp-title">
        <div className="lp-hero-bg" aria-hidden="true" />
        <div className="lp-hero-inner">
          <div className="lp-hero-text">
            <p className="lp-pill"><Orbit /> {t("NASA Space Apps Challenge 2026")}</p>
            <h1 id="lp-title" className="lp-title">
              {t("Is this place")} <span className="lp-grad">{t("really")}</span> {t("changing?")}
            </h1>
            <p className="lp-lede">{t("MegavirTrace turns NASA satellite and climate records into honest answers you can check: what is changing, where, how fast, and whether it is more than chance.")}</p>
            <div className="lp-cta">
              <Link className="button primary lp-btn" href="/explore">{t("Start exploring")} <Icon d={ICONS.arrow} size={17} /></Link>
              <Link className="button lp-btn" href="/cases">{t("Solve a detective case")}</Link>
              <a className="button lp-btn lp-btn-github" href={GITHUB_URL} target="_blank" rel="noopener noreferrer" aria-label={t("GitHub: the source code (opens in a new tab)")}>
                <GitHubIcon size={18} />
                GitHub
              </a>
            </div>
            <div className="lp-try">
              <span className="lp-try-label">{t("Try:")}</span>
              <ul>
                {TRY.map((x) => <li key={x.href}><Link className="lp-chip" href={x.href}>{t(x.label)}</Link></li>)}
              </ul>
            </div>
          </div>
          <LiveCard summary={summary} failed={failed} />
        </div>
      </section>

      {summary?.hero && <Stripes hero={summary.hero} />}

      <section className="lp-stats lp-reveal" aria-label={t("MegavirTrace in numbers")} aria-busy={!summary}>
        {summary ? (
          <>
            <div className="lp-stat"><strong><CountUp value={summary.variables} /></strong><span>{t("measurements of the Earth")}</span></div>
            <div className="lp-stat"><strong><CountUp value={summary.products.length} /></strong><span>{t("NASA data products")}</span></div>
            <div className="lp-stat"><strong>{summary.first_month?.slice(0, 4) ?? "—"}</strong><span>{t("first year on record")}</span></div>
            <div className="lp-stat"><strong><CountUp value={summary.cases} /></strong><span>{t("detective cases")}</span></div>
          </>
        ) : (
          [0, 1, 2, 3].map((k) => <div key={k} className="lp-stat"><div className="lp-skel lp-skel-stat" /><div className="lp-skel lp-skel-line" /></div>)
        )}
      </section>

      <Section id="lp-what" eyebrow={t("What you can do")} title={t("One question, many ways to answer it")}>
        <ul className="lp-features">
          {features.map((f) => (
            <li key={f.href} className={`lp-feature card tone-${f.tone}`}>
              <span className="lp-feature-icon"><Icon d={f.icon} size={22} /></span>
              <h3><Link className="stretched-link" href={f.href}>{f.title}</Link></h3>
              <p>{f.text}</p>
              <span className="lp-feature-go" aria-hidden="true"><Icon d={ICONS.arrow} size={16} /></span>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="lp-how" eyebrow={t("How a verdict is made")} title={t("From satellite to sentence, in four checked steps")}>
        <ol className="lp-steps">
          {steps.map((s, i) => (
            <li key={i} className="lp-step">
              <span className="lp-step-n" aria-hidden="true">{i + 1}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="lp-cases" eyebrow={t("Detective cases")} title={t("Real events, solved with real measurements")}>
        {cases === null ? (
          <div className="lp-case-grid" aria-busy="true">
            {FEATURED.map((id) => <div key={id} className="card lp-case lp-case-skel"><div className="lp-skel lp-skel-line" /><div className="lp-skel lp-skel-title" /><div className="lp-skel lp-skel-chart" /></div>)}
            <span className="visually-hidden" role="status">{t("Computing the cases from the measurements…")}</span>
          </div>
        ) : cases.length > 0 && (
          <ul className="lp-case-grid">
            {cases.map((c) => (
              <li key={c.id} className="card lp-case">
                <span className="lp-eyebrow small">{theme(c.theme)} · {c.when}</span>
                <h3><Link className="stretched-link" href={`/cases/${c.id}`}>{c.title}</Link></h3>
                {c.evidence && (
                  <>
                    <Sparkline values={c.evidence.chart.series[0]?.values ?? []} highlight={c.evidence.chart.highlight} width={260} height={56} label={c.evidence.title} />
                    <p className="lp-case-finding">{c.evidence.finding}</p>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="lp-more"><Link href="/cases">{t("See all {n} cases", { n: nCases })} <Icon d={ICONS.arrow} size={15} /></Link></p>
      </Section>

      <section className="lp-section lp-honest lp-reveal" aria-labelledby="lp-honest">
        <div>
          <p className="lp-eyebrow">{t("Honest by design")}</p>
          <h2 id="lp-honest" className="lp-h2">{t("Every number can be checked")}</h2>
          <p className="lp-text">{t("A trend line can be drawn through any noise. MegavirTrace only calls a change real when the data support it, and says how many more years are needed when they do not.")}</p>
          <p><Link href="/methods">{t("Read the method")} <Icon d={ICONS.arrow} size={15} /></Link></p>
        </div>
        <ul className="lp-promises">
          {promises.map((p) => <li key={p}><span className="lp-check"><Icon d={ICONS.check} size={20} /></span>{p}</li>)}
        </ul>
      </section>

      <Section id="lp-data" eyebrow={t("Built on NASA open data")} title={t("Every measurement comes from a published NASA data product")} className="lp-data">
        <ul className="lp-products">
          {(summary?.products ?? []).map((p) => <li key={p}>{p}</li>)}
        </ul>
        {summary && summary.themes.length > 0 && (
          <p className="small muted">{t("Themes")}: {summary.themes.map(theme).join(" · ")}{summary.first_month && summary.last_month ? ` · ${summary.first_month.slice(0, 4)}–${summary.last_month.slice(0, 4)}` : ""}</p>
        )}
      </Section>

      <section className="lp-final lp-reveal" aria-labelledby="lp-final">
        <h2 id="lp-final">{t("Pick a place you care about.")}</h2>
        <p>{t("Your town, your country, a sea you love: see what the measurements really say.")}</p>
        <div className="lp-cta">
          <Link className="button lp-btn lp-btn-light" href="/explore">{t("Start exploring")} <Icon d={ICONS.arrow} size={17} /></Link>
          <Link className="button lp-btn lp-btn-ghost" href="/ask">{t("Ask the AI")}</Link>
        </div>
        <p className="lp-final-note small">{t("A trend is not a cause.")}</p>
      </section>
    </div>
  );
}
