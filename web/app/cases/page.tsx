"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Sparkline from "@/components/Sparkline";
import { apiGet, type CaseSummary } from "@/lib/api";
import { THEME_ES, useI18n } from "@/lib/i18n";

// Detective cases: real events and documented changes, each tied to specific regions and NASA
// variables.  Every card shows a finding and a small chart computed from the stored measurements.

const PIN = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21Z" />
    <circle cx="12" cy="9.5" r="2.5" />
  </svg>
);
const CHECK = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="m8 12 3 3 5-6" />
  </svg>
);

export default function CasesPage() {
  const { lang, t } = useI18n();
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    let gone = false;
    setError(null);
    apiGet<{ cases: CaseSummary[] }>("/cases", { lang })
      .then((r) => { if (!gone) setCases(r.cases); })
      .catch((e: Error) => { if (!gone) setError(e.message); });
    return () => { gone = true; };
  }, [lang]);

  const themeName = (th: string) => (lang === "es" ? THEME_ES[th] ?? th : th);
  const filters = useMemo(() => {
    if (!cases) return [];
    const themes = [...new Set(cases.map((c) => c.theme))];
    return [
      { id: "all", label: t("All"), n: cases.length },
      { id: "event", label: t("Events"), n: cases.filter((c) => c.kind === "event").length },
      { id: "change", label: t("Long-term changes"), n: cases.filter((c) => c.kind === "change").length },
      ...themes.map((th) => ({ id: `theme:${th}`, label: lang === "es" ? THEME_ES[th] ?? th : th, n: cases.filter((c) => c.theme === th).length })),
    ];
  }, [cases, lang, t]);
  const shown = (cases ?? []).filter((c) =>
    filter === "all" ? true : filter === "event" || filter === "change" ? c.kind === filter : c.theme === filter.slice(6),
  );

  return (
    <div>
      <h1>{t("Detective cases")}</h1>
      <p className="lede">
        {t("Real events and documented changes, investigated step by step with NASA measurements of specific places. The stories only say what happened in the world and where to look: every number is computed from the stored data.")}
      </p>
      {lang === "es" && <p className="small muted">{t("The case stories are in English for now; every finding is written in your language from the computed results.")}</p>}

      {error && <p className="error" role="alert">{error}</p>}
      {!cases && !error && <p className="spinner-note" role="status">{t("Computing the cases from the measurements…")}</p>}

      {cases && (
        <>
          <div className="chip-list case-filters" role="group" aria-label={t("Show cases")}>
            {filters.map((f) => (
              <button key={f.id} type="button" className="chip" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                {f.label} <span className="chip-count">({f.n})</span>
              </button>
            ))}
          </div>
          <ul className="case-grid">
            {shown.map((c) => (
              <li key={c.id}>
                <article className="card case-card">
                  <div className="case-top">
                    <span className="eyebrow">{themeName(c.theme)}</span>
                    {c.data_kind === "real" && <span className="badge badge-real">{CHECK} {t("Real NASA measurements")}</span>}
                  </div>
                  <h2 className="case-title"><Link href={`/cases/${c.id}`} className="stretched-link">{c.title}</Link></h2>
                  <p className="case-where">{PIN} <span>{c.where} · {c.when}</span></p>
                  <p className="case-story">{c.story}</p>
                  {c.evidence && (
                    <div className="case-evidence">
                      <Sparkline
                        values={c.evidence.chart.series[0]?.values ?? []}
                        highlight={c.evidence.chart.highlight}
                        label={t("Small chart: {title}", { title: c.evidence.title })}
                      />
                      <p><span className="evidence-label">{t("Measured")}</span> {c.evidence.finding}</p>
                    </div>
                  )}
                  <p className="case-foot">
                    {t("{n} steps", { n: c.n_steps })} · {c.variables.map((v) => v.name).join(" · ")}
                  </p>
                </article>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
