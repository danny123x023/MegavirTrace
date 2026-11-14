"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import EarthMap from "@/components/EarthMap";
import { type Chosen, PlacePicker, VariablePicker } from "@/components/Pickers";
import { DataFlag, Downloads } from "@/components/Result";
import TrendChart from "@/components/TrendChart";
import { apiGet, apiPost, type Catalog, type CompareResult } from "@/lib/api";
import { fmt, fmtP, fmtSigned } from "@/lib/format";
import { useI18n, varText } from "@/lib/i18n";

type Opposites = {
  rising: { place: string; name: string; per_decade: number }[];
  falling: { place: string; name: string; per_decade: number }[];
  pairs: { a: { place: string; name: string }; b: { place: string; name: string }; headline: string; difference_per_decade: number }[];
  note: string;
};

export default function ComparePage() {
  const { lang, t } = useI18n();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [variable, setVariable] = useState("");
  const [a, setA] = useState<Chosen | null>(null);
  const [b, setB] = useState<Chosen | null>(null);
  const [mode, setMode] = useState("annual");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [opp, setOpp] = useState<Opposites | null>(null);
  const [oppLoading, setOppLoading] = useState(false);

  useEffect(() => {
    apiGet<Catalog>("/variables").then((c) => {
      setCatalog(c);
      const real = c.variables.filter((v) => v.data?.kind === "real");
      const pick = real.find((v) => v.id === "temp_change") ?? real[0] ?? c.variables.find((v) => v.data);
      if (pick) {
        setVariable(pick.id);
        if (pick.data?.kind === "real") {
          setA({ region: { place: "preset:siberia" }, label: "Siberia" });
          setB({ region: { place: "preset:north_atlantic_warming_hole" }, label: "North Atlantic 'warming hole'" });
        }
      }
    }).catch((e) => setError(e.message));
  }, []);

  const varInfo = useMemo(() => catalog?.variables.find((v) => v.id === variable), [catalog, variable]);

  const run = useCallback(async () => {
    if (!variable || !a || !b) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await apiPost<CompareResult>("/analysis/compare", { variable, region_a: a.region, region_b: b.region, mode, lang }));
    } catch (e) {
      setError((e as Error).message);
    }
    setLoading(false);
  }, [variable, a, b, mode, lang]);

  useEffect(() => { run(); }, [run]);
  useEffect(() => setOpp(null), [variable]);

  const c = result?.comparison;
  const d = c?.difference;

  return (
    <div>
      <h1>{t("Compare two places")}</h1>
      <p className="lede">
        Are two regions really changing differently? The test runs on the year-by-year <em>difference</em> between them, so the ups
        and downs they share cancel out. Regions that move together are not under-tested, and regions that move apart are not over-tested.
      </p>

      <div className="filters" role="search" aria-label="Choose a variable and two regions">
        <VariablePicker catalog={catalog} value={variable} onChange={setVariable} />
        <PlacePicker label="Region A" value={a} onChange={setA} />
        <PlacePicker label="Region B" value={b} onChange={setB} />
        <div className="field">
          <span className="label" id="cmp-mode">How</span>
          <div className="segmented" role="group" aria-labelledby="cmp-mode">
            {[["annual", "Yearly"], ["monthly", "Monthly anomalies"]].map(([k, l]) => (
              <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>{l}</button>
            ))}
          </div>
        </div>
      </div>

      {varInfo?.data && varInfo.data.kind !== "real" && <DataFlag kind={varInfo.data.kind} />}
      {error && <p className="error" role="alert">{error}</p>}
      {!result && loading && <p className="spinner-note" role="status">Comparing…</p>}

      {result && c && d && (
        <div style={{ opacity: loading ? 0.55 : 1 }} aria-busy={loading}>
          <div className="grid-2">
            <div className="stack">
              <section className="card verdict" aria-labelledby="cmp-h">
                <DataFlag kind={result.data.kind} />
                <span className="status-pill"><span aria-hidden="true">{d.significant ? "▲▼" : "○"}</span>{d.significant ? t("The trends really differ") : t("No clear difference")}</span>
                <h2 id="cmp-h">{result.verdict.headline}</h2>
                {result.verdict.sentences.map((s, i) => <p key={i}>{s}</p>)}
                <ul className="caveats">{result.verdict.caveats.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </section>
              <section className="card" aria-label="Both regions">
                <TrendChart
                  title={`${varText(result.variable, lang)}: ${result.region_a.name} — ${result.region_b.name}`}
                  labels={c.labels}
                  t={c.t}
                  units={result.units}
                  series={[
                    { key: "a", label: `A: ${result.region_a.name}`, color: "var(--series-1)", values: c.a },
                    { key: "b", label: `B: ${result.region_b.name}`, color: "var(--series-2)", values: c.b },
                  ]}
                />
              </section>
              <section className="card" aria-label="The difference">
                <TrendChart
                  title={`Difference, A minus B (${result.units})`}
                  labels={c.labels}
                  t={c.t}
                  units={result.units}
                  series={[{ key: "d", label: "A minus B", color: "var(--series-1)", values: c.diff }]}
                  zeroLine
                />
              </section>
            </div>
            <div className="stack">
              <section className="card" aria-label="Map of both regions">
                <h2>{t("The two regions")}</h2>
                <EarthMap outlines={[{ geometry: result.region_a.geometry, bbox: result.region_a.bbox }, { geometry: result.region_b.geometry, bbox: result.region_b.bbox }]} height={320} />
              </section>
              <div className="tiles">
                <div className="tile"><div className="label">{t("Difference in trend")}</div><div className="value">{fmtSigned(d.slope_per_decade)} {result.units}</div><div className="sub">per decade · 95% range {fmtSigned(d.ci_low_per_decade)} to {fmtSigned(d.ci_high_per_decade)}</div></div>
                <div className="tile"><div className="label">{t("Test on the difference")}</div><div className="value">p {fmtP(d.p).startsWith("<") ? fmtP(d.p) : "= " + fmtP(d.p)}</div><div className="sub">{t("both tests must agree")}</div></div>
                <div className="tile"><div className="label">{t("Smallest detectable")}</div><div className="value">{fmt(d.min_detectable_per_decade)} {result.units}</div><div className="sub">{t("per decade, with this record")}</div></div>
                <div className="tile"><div className="label">{t("How much they move together")}</div><div className="value">r = {fmt(c.correlation, 2)}</div><div className="sub">{t("shared ups and downs cancel in the difference")}</div></div>
                <div className="tile"><div className="label">{t("Trend in A")}</div><div className="value">{fmtSigned(c.stats_a.per_decade?.sen ?? c.stats_a.sen.slope * 10)} {result.units}</div><div className="sub">per decade · {c.stats_a.significant ? "significant" : "not significant"}</div></div>
                <div className="tile"><div className="label">{t("Trend in B")}</div><div className="value">{fmtSigned(c.stats_b.per_decade?.sen ?? c.stats_b.sen.slope * 10)} {result.units}</div><div className="sub">per decade · {c.stats_b.significant ? "significant" : "not significant"}</div></div>
              </div>
              <Downloads id={result.id} />
            </div>
          </div>
        </div>
      )}

      <section className="card" style={{ marginTop: 20 }} aria-labelledby="opp-h">
        <h2 id="opp-h">{t("Find regions with opposite trends")}</h2>
        <p className="muted small">
          Scans the preset regions for robust, significant trends in {varInfo?.name.toLowerCase() ?? "this variable"} that point in opposite
          directions, then tests each pair&apos;s difference directly. The first scan of a variable can take a minute; results are stored.
        </p>
        <button type="button" disabled={oppLoading || !variable} onClick={async () => {
          setOppLoading(true);
          try { setOpp(await apiGet<Opposites>("/analysis/opposites", { variable })); } catch (e) { setError((e as Error).message); }
          setOppLoading(false);
        }}>{oppLoading ? t("Scanning presets…") : t("Find opposite trends")}</button>
        {opp && (
          <div style={{ marginTop: 12 }}>
            {opp.pairs.length === 0 && <p>No pair of preset regions has robust, significant trends in opposite directions for this variable.</p>}
            <ul>
              {opp.pairs.map((p, i) => (
                <li key={i}>
                  <button type="button" className="chip" onClick={() => { setA({ region: { place: p.a.place }, label: p.a.name }); setB({ region: { place: p.b.place }, label: p.b.name }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                    Compare
                  </button>{" "}
                  {p.headline}
                </li>
              ))}
            </ul>
            <p className="small muted">{opp.rising.length} presets rising, {opp.falling.length} falling (robust and significant). {opp.note}</p>
          </div>
        )}
      </section>
    </div>
  );
}
