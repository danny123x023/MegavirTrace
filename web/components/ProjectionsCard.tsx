"use client";

import { useEffect, useRef, useState } from "react";
import TrendChart from "@/components/TrendChart";
import { apiGet, apiPost } from "@/lib/api";
import { fmtSigned } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

type Scenario = { label: string; median: (number | null)[]; min: (number | null)[]; max: (number | null)[]; models: number[] };
type Result = {
  units: string; change_kind: string; models_used: string[]; baseline_years: number[]; years: number[];
  scenarios: Record<string, Scenario>; observed: null | { t: (number | null)[]; change: (number | null)[]; labels: string[] };
  caveats: string[]; source: string;
};
type Status = { status: string; done?: number; total?: number; error?: string | null; result?: Result; summary?: string[] };

const PAIRED = new Set(["air_temp", "temp_change", "daily_high", "nightly_low", "rainfall"]);

export default function ProjectionsCard({ analysisId, variable }: { analysisId: string; variable: string }) {
  const { lang, t } = useI18n();
  const [st, setSt] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setSt(null); setError(null);
    if (!PAIRED.has(variable)) return;
    apiGet<Status>("/context/projections", { analysis_id: analysisId, lang }).then((s) => {
      if (s.status === "done" || s.status === "running") setSt(s);
      if (s.status === "running") poll();
    }).catch(() => {});
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [analysisId, variable, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!PAIRED.has(variable)) return null;

  function poll() {
    timer.current = setTimeout(async () => {
      try {
        const s = await apiGet<Status>("/context/projections", { analysis_id: analysisId, lang });
        setSt(s);
        if (s.status === "running") poll();
        if (s.status === "error") setError(s.error ?? "failed");
      } catch (e) { setError((e as Error).message); }
    }, 3000);
  }

  async function start() {
    setError(null);
    try {
      const s = await apiPost<Status>("/context/projections", { analysis_id: analysisId });
      setSt(s);
      if (s.status === "running") poll();
      if (s.status === "done") setSt(await apiGet<Status>("/context/projections", { analysis_id: analysisId, lang }));
    } catch (e) { setError((e as Error).message); }
  }

  const r = st?.result;
  const tAxis: number[] = [];
  const obsVals: (number | null)[] = [];
  const s245: (number | null)[] = [];
  const s585: (number | null)[] = [];
  const labels: string[] = [];
  if (r) {
    const pts = new Map<number, { o?: number | null; a?: number | null; b?: number | null; label: string }>();
    r.observed?.t.forEach((x, i) => { if (x !== null) pts.set(x, { o: r.observed!.change[i], label: r.observed!.labels[i] }); });
    r.years.forEach((y, i) => {
      const key = y + 0.5;
      const cur = pts.get(key) ?? { label: String(y) };
      pts.set(key, { ...cur, a: r.scenarios.ssp245?.median[i] ?? null, b: r.scenarios.ssp585?.median[i] ?? null });
    });
    [...pts.keys()].sort((x, y) => x - y).forEach((k) => {
      const p = pts.get(k)!;
      tAxis.push(k); labels.push(p.label); obsVals.push(p.o ?? null); s245.push(p.a ?? null); s585.push(p.b ?? null);
    });
  }

  return (
    <section className="card" aria-labelledby="proj-h">
      <h2 id="proj-h">{lang === "es" ? "Proyecciones climáticas (NASA NEX-GDDP-CMIP6)" : "Climate projections (NASA NEX-GDDP-CMIP6)"}</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        {lang === "es"
          ? "Lo que simulan cinco modelos climáticos bajo dos caminos de emisiones, junto al cambio observado. Contexto, no pronóstico: no forma parte de las pruebas de tendencia."
          : "What five climate models simulate under two emissions paths, beside the observed change. Context, not a forecast: never part of the trend tests."}
      </p>
      {!st && (
        <button type="button" onClick={start}>
          {lang === "es" ? "Calcular proyecciones (unos minutos la primera vez)" : "Compute projections (a few minutes the first time)"}
        </button>
      )}
      {st?.status === "running" && (
        <p className="spinner-note" role="status">
          {lang === "es" ? "Calculando en los servidores de la NASA…" : "Computing on NASA's servers…"} {st.done ?? 0} / {st.total ?? 0}
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {r && st?.status === "done" && (
        <div className="stack" style={{ gap: 10 }}>
          {st.summary?.map((x) => <p key={x} style={{ margin: 0 }}>{x}</p>)}
          <TrendChart
            title={lang === "es" ? `Cambio respecto a ${r.baseline_years[0]}–${r.baseline_years[r.baseline_years.length - 1]}` : `Change from ${r.baseline_years[0]}–${r.baseline_years[r.baseline_years.length - 1]}`}
            labels={labels}
            t={tAxis}
            units={r.units}
            series={[
              { key: "obs", label: lang === "es" ? "Observado" : "Observed", color: "var(--series-1)", values: obsVals, markers: false },
              { key: "a", label: r.scenarios.ssp245?.label ?? "SSP2-4.5", color: "var(--series-2)", values: s245, connect: true },
              { key: "b", label: r.scenarios.ssp585?.label ?? "SSP5-8.5", color: "var(--series-3)", values: s585, connect: true },
            ]}
            zeroLine
            height={260}
          />
          <div className="table-scroll" tabIndex={0} role="region" aria-label={lang === "es" ? "Rangos de los modelos" : "Model ranges"}>
            <table className="data">
              <thead><tr><th scope="col">{lang === "es" ? "Año" : "Year"}</th>{Object.entries(r.scenarios).map(([k, v]) => <th scope="col" key={k}>{v.label}</th>)}</tr></thead>
              <tbody>
                {r.years.map((y, i) => (
                  <tr key={y}>
                    <td>{y}</td>
                    {Object.entries(r.scenarios).map(([k, v]) => (
                      <td key={k}>{v.median[i] === null ? "—" : `${fmtSigned(v.median[i])} (${fmtSigned(v.min[i])} … ${fmtSigned(v.max[i])})`}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="caveats">{r.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
          <p className="small muted" style={{ margin: 0 }}>{t("Source:")} {r.source}. {lang === "es" ? "Modelos" : "Models"}: {r.models_used.join(", ")}.</p>
        </div>
      )}
    </section>
  );
}
