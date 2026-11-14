"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import LagChart from "@/components/LagChart";
import { type Chosen, PlacePicker, VariablePicker } from "@/components/Pickers";
import { DataFlag } from "@/components/Result";
import TrendChart from "@/components/TrendChart";
import { apiGet, apiPost, type Catalog, exportUrl, type Verdict } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useI18n, varText } from "@/lib/i18n";

type Related = {
  id: string;
  variable_a: { id: string; name: string };
  variable_b: { id: string; name: string };
  region: { name: string };
  relationship: {
    lags: number[]; r: (number | null)[]; p: (number | null)[]; n: number[]; best_lag: number; best_r: number;
    p_adjusted: number; n_lags_tested: number; n_eff: number; r_needed: number | null; significant: boolean;
    labels: string[]; months: number[]; a_std: (number | null)[]; b_std: (number | null)[]; variance_inflation: number;
  };
  verdict: Verdict;
  data_kind: string;
};

export default function RelatedPage() {
  const { lang, t: tr } = useI18n();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [place, setPlace] = useState<Chosen | null>(null);
  const [maxLag, setMaxLag] = useState(12);
  const [res, setRes] = useState<Related | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<Catalog>("/variables").then((c) => {
      setCatalog(c);
      const loaded = c.variables.filter((v) => v.data?.kind === "real");
      if (loaded.length >= 2) {
        setA(loaded.find((v) => v.id === "temp_change")?.id ?? loaded[0].id);
        setB(loaded.find((v) => v.id === "land_water")?.id ?? loaded[1].id);
        setPlace({ region: { place: "admin1:US-TX" }, label: "Texas" });
      } else {
        const any = c.variables.filter((v) => v.data);
        if (any.length >= 2) { setA(any[0].id); setB(any[1].id); }
      }
    }).catch((e) => setError(e.message));
  }, []);

  const run = useCallback(async () => {
    if (!a || !b || !place) return;
    if (a === b) { setError("Choose two different variables."); return; }
    setBusy(true); setError(null);
    try { setRes(await apiPost<Related>("/analysis/related", { variable_a: a, variable_b: b, region: place.region, max_lag: maxLag, lang })); }
    catch (e) { setError((e as Error).message); }
    setBusy(false);
  }, [a, b, place, maxLag, lang]);
  useEffect(() => { run(); }, [run]);

  const rel = res?.relationship;
  const t = useMemo(() => rel?.months.map((m) => m / 12 + 1 / 24) ?? [], [rel]);

  return (
    <div>
      <h1>{tr("Do two things move together?")}</h1>
      <p className="lede">
        Pick a place and two variables. MegavirTrace removes each seasonal cycle and long-term trend, then asks whether the month-to-month
        ups and downs line up, with a delay of up to {maxLag} months. <strong>Related is not caused by.</strong>
      </p>
      <div className="filters" role="search" aria-label="Choose a place and two variables">
        <PlacePicker label="Where" value={place} onChange={setPlace} />
        <VariablePicker catalog={catalog} value={a} onChange={setA} label="Variable A" />
        <VariablePicker catalog={catalog} value={b} onChange={setB} label="Variable B" />
        <div className="field">
          <label htmlFor="maxlag">{tr("Longest delay")}</label>
          <select id="maxlag" value={maxLag} onChange={(e) => setMaxLag(Number(e.target.value))}>
            {[0, 3, 6, 12, 24].map((k) => <option key={k} value={k}>{k === 0 ? tr("same month only") : tr("{n} months", { n: k })}</option>)}
          </select>
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!res && busy && <p className="spinner-note" role="status">Comparing…</p>}
      {res && rel && (
        <div style={{ opacity: busy ? 0.55 : 1 }} aria-busy={busy}>
          <div className="grid-2">
            <section className="card verdict" aria-labelledby="rel-h">
              <DataFlag kind={res.data_kind} />
              <span className="status-pill"><span aria-hidden="true">{rel.significant ? "⇄" : "○"}</span>{rel.significant ? tr("They move together") : tr("No clear relationship")}</span>
              <h2 id="rel-h">{res.verdict.headline}</h2>
              {res.verdict.sentences.map((s, i) => <p key={i}>{s}</p>)}
              <ul className="caveats">{res.verdict.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
              <p className="small muted">
                Independent pairs after allowing for memory: about {Math.round(rel.n_eff)} (variance × {fmt(rel.variance_inflation, 2)}).{" "}
                <a href={exportUrl(res.id, "csv")} download>CSV</a> · <a href={exportUrl(res.id, "json")} download>JSON</a>
              </p>
            </section>
            <section className="card" aria-label="Correlation by lag">
              <LagChart lags={rel.lags} r={rel.r} p={rel.p} n={rel.n} best={rel.best_lag} rNeeded={rel.r_needed}
                labelA={res.variable_a.name.toLowerCase()} labelB={res.variable_b.name.toLowerCase()} />
            </section>
          </div>
          <section className="card" style={{ marginTop: 16 }} aria-label="Both series">
            <TrendChart
              title={`${res.variable_a.name} and ${res.variable_b.name} — ${res.region.name}, standardized anomalies`}
              labels={rel.labels}
              t={t}
              units="standard deviations"
              series={[
                { key: "a", label: `A: ${res.variable_a.name}`, color: "var(--series-1)", values: rel.a_std, markers: false },
                { key: "b", label: `B: ${res.variable_b.name}`, color: "var(--series-2)", values: rel.b_std, markers: false },
              ]}
              zeroLine
              height={260}
            />
            <p className="small muted">Each series is shown in its own standard deviations (z-scores) after removing its seasonal cycle and trend, so both fit one axis.</p>
          </section>
        </div>
      )}
    </div>
  );
}
