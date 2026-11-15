"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import EarthMap from "@/components/EarthMap";
import Panel from "@/components/Panel";
import TrendChart from "@/components/TrendChart";
import { ApiError, apiGet, type CaseDetail, type CaseStep, exportUrl } from "@/lib/api";
import { fmt } from "@/lib/format";
import { THEME_ES, useI18n } from "@/lib/i18n";

// One detective case: the story (what happened), the question, then one step at a time: where to
// look, the chart with the event marked, and the finding written from the computed numbers.

type Detail = CaseDetail & { next?: { id: string; title: string } };

function StepChart({ step }: { step: CaseStep }) {
  const { t } = useI18n();
  const ch = step.chart;
  if (!ch) return null;
  const colors = ["var(--series-1)", "var(--series-3)"];
  const series = ch.series.map((s, k) => ({
    key: s.key,
    label: s.label ?? step.variable.name,
    color: colors[k] ?? "var(--series-1)",
    values: s.values,
  }));
  return (
    <TrendChart
      title={ch.kind === "month" ? (ch.title ?? step.variable.name) : `${step.variable.name} · ${step.region ?? ""}`}
      labels={ch.labels}
      t={ch.t ?? ch.labels.map((_, i) => i)}
      series={series}
      units={ch.units}
      height={260}
      trend={ch.trend ? { line: ch.trend.line, slopeLow: ch.trend.low, slopeHigh: ch.trend.high, label: t("Trend: {x} per decade", { x: ch.per_decade_label ?? "" }) } : null}
      highlight={ch.highlight}
      refLine={ch.kind === "month" && ch.mean !== undefined ? { value: ch.mean, label: t("usual: {v}", { v: `${fmt(ch.mean, 3)} ${ch.units}` }) } : null}
    />
  );
}

function exploreHref(q: Record<string, string | number>) {
  return "/explore?" + new URLSearchParams(Object.entries(q).map(([k, v]) => [k, String(v)])).toString();
}

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const { lang, t } = useI18n();
  const [c, setC] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(1);
  const revealed = useRef(1);

  useEffect(() => {
    let gone = false;
    setError(null);
    apiGet<Detail>(`/cases/${encodeURIComponent(id)}`, { lang })
      .then((r) => { if (!gone) setC(r); })
      .catch((e: Error) => { if (!gone) setError(e instanceof ApiError && e.status === 404 ? t("Case not found.") : e.message); });
    return () => { gone = true; };
  }, [id, lang, t]);

  useEffect(() => { setShown(1); revealed.current = 1; }, [id]);

  // a newly shown step takes the focus, so keyboard and screen-reader users land on it
  useEffect(() => {
    if (shown > revealed.current && c) {
      // the first step just shown (or the summary, when no step was left)
      const target = revealed.current < c.steps.length ? `step-${revealed.current}` : "case-summary";
      document.getElementById(target)?.focus();
    }
    revealed.current = shown;
  }, [shown, c]);

  if (error) return <div><p><Link href="/cases">← {t("All detective cases")}</Link></p><p className="error" role="alert">{error}</p></div>;
  if (!c) return <p className="spinner-note" role="status">{t("Loading the case…")}</p>;

  const n = c.steps.length;
  const all = shown > n;
  return (
    <div className="case-page">
      <p className="small"><Link href="/cases">← {t("All detective cases")}</Link></p>
      <div className="case-top">
        <span className="eyebrow">{lang === "es" ? THEME_ES[c.theme] ?? c.theme : c.theme}</span>
        <span className="badge">{c.kind === "event" ? t("Event") : t("Long-term change")}</span>
        {c.data_kind === "real" && <span className="badge badge-real">{t("Real NASA measurements")}</span>}
      </div>
      <h1>{c.title}</h1>
      {lang === "es" && <p className="small muted">{t("The case stories are in English for now; every finding is written in your language from the computed results.")}</p>}

      <div className="case-intro">
        <section className="case-story-block" aria-labelledby="what-happened">
          <h2 id="what-happened" className="step-kicker">{t("What happened")}</h2>
          <p className="lede" style={{ marginTop: 4 }}>{c.story}</p>
          <dl className="case-facts">
            <div><dt>{t("Where")}</dt><dd>{c.where}</dd></div>
            <div><dt>{t("When")}</dt><dd>{c.when}</dd></div>
            <div><dt>{t("Data")}</dt><dd>{c.variables.map((v) => `${v.name} (${v.product})`).join(" · ")}</dd></div>
          </dl>
          <div className="case-question">
            <span className="step-kicker">{t("The question")}</span>
            <p>{c.question}</p>
          </div>
        </section>
        <Panel className="case-map" aria-label={t("Where the case takes place")}>
          <h2 style={{ marginTop: 0 }}>{t("Where the case takes place")}</h2>
          <EarthMap outlines={c.regions.map((r) => ({ bbox: r.bbox, label: r.label }))} height={300} />
          <p className="small muted" style={{ margin: "8px 0 0" }}>{c.regions.map((r) => r.label).join(" · ")}</p>
        </Panel>
      </div>

      <ol className="case-steps">
        {c.steps.slice(0, Math.min(shown, n)).map((s, i) => (
          <li key={i}>
            <Panel aria-labelledby={`step-${i}`} className="case-step">
              <span className="step-kicker">{t("Step {k} of {n}", { k: i + 1, n })}</span>
              <h2 id={`step-${i}`} tabIndex={-1}>{s.title}</h2>
              <p className="case-look"><strong>{t("Where to look")}:</strong> {s.look}</p>
              {s.error ? (
                <p className="error" role="note">{t("This step could not be computed: {error}", { error: s.error })}</p>
              ) : (
                <>
                  <div className="case-finding">
                    <span className="step-kicker">{t("What the measurements show")}</span>
                    <p>{s.finding}</p>
                  </div>
                  <StepChart step={s} />
                </>
              )}
              <p className="case-source small muted">
                {t("Data")}: {s.variable.name} · {s.variable.doi ? <a href={`https://doi.org/${s.variable.doi}`} target="_blank" rel="noopener">{s.variable.product}</a> : s.variable.product}
                {" · "}<Link href={exploreHref(s.explore)}>{t("See the full record in Explore")}</Link>
                {s.analysis_id && <>{" · "}<a href={exportUrl(s.analysis_id, "csv")}>{t("Download the data (CSV)")}</a></>}
              </p>
            </Panel>
          </li>
        ))}
      </ol>

      {!all && (
        <div className="row case-next">
          <button type="button" className="primary" onClick={() => setShown(shown + 1)}>
            {shown < n ? t("Next step: {title}", { title: c.steps[shown].title }) : t("See the case summary")}
          </button>
          {shown < n && <button type="button" onClick={() => setShown(n + 1)}>{t("Show all steps")}</button>}
        </div>
      )}

      {all && (
        <Panel className="case-summary" aria-labelledby="case-summary">
          <h2 id="case-summary" tabIndex={-1} style={{ marginTop: 0 }}>{t("Case summary: what the measurements say")}</h2>
          <ol className="case-findings">
            {c.steps.map((s, i) => (
              <li key={i}><strong>{s.title}</strong> {s.error ? t("Not computed.") : s.finding}</li>
            ))}
          </ol>
          <div className="case-question">
            <span className="step-kicker">{t("The lesson")}</span>
            <p>{c.takeaway}</p>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>
            {t("Skills")}: {c.skills.join(" · ")}
          </p>
          <div className="row" style={{ marginTop: 14 }}>
            <Link className="button primary" href={`/explore?v=${c.variables[0]?.id ?? ""}`}>{t("Investigate your own area")}</Link>
            {c.next && <Link className="button" href={`/cases/${c.next.id}`}>{t("Next case")}: {c.next.title} →</Link>}
          </div>
        </Panel>
      )}
    </div>
  );
}
