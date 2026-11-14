"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import EarthMap from "@/components/EarthMap";
import GlobeCard, { type GlobeSite } from "@/components/GlobeCard";
import { type Chosen, ModeControls, type ModeState, PlacePicker, VariablePicker } from "@/components/Pickers";
import { Downloads, ExplainWithAI, StatTiles, VerdictCard } from "@/components/Result";
import TrendChart from "@/components/TrendChart";
import { apiGet, apiPost, type Catalog, type Region, type TrendResult } from "@/lib/api";
import { MODE_LABEL } from "@/lib/format";

function regionFromParams(sp: URLSearchParams): Chosen | null {
  const place = sp.get("place");
  if (place) return { region: { place }, label: sp.get("label") ?? place };
  const bbox = sp.get("bbox");
  if (bbox) {
    const b = bbox.split(",").map(Number);
    if (b.length === 4 && b.every(Number.isFinite)) return { region: { bbox: b }, label: `Box ${b.join(", ")}` };
  }
  return null;
}

export default function ExploreClient() {
  const sp = useSearchParams();
  const router = useRouter();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [variable, setVariable] = useState(sp.get("v") ?? "");
  const [chosen, setChosen] = useState<Chosen | null>(regionFromParams(new URLSearchParams(sp.toString())));
  const [mode, setMode] = useState<ModeState>({ mode: sp.get("mode") ?? "annual", season: sp.get("season") ?? "JJA", start: sp.get("start") ?? "", end: sp.get("end") ?? "" });
  const [result, setResult] = useState<TrendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [globeSites, setGlobeSites] = useState<GlobeSite[]>([]);
  const ctl = useRef<AbortController | null>(null);

  useEffect(() => {
    apiGet<Catalog>("/variables").then((c) => {
      setCatalog(c);
      if (!variable || !c.variables.find((v) => v.id === variable && v.data)) {
        const real = c.variables.filter((v) => v.data?.kind === "real");
        const pick = real.find((v) => v.id === "temp_change") ?? real[0] ?? c.variables.find((v) => v.data);
        if (pick) setVariable(pick.id);
      }
    }).catch((e) => setError(String(e.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const varInfo = useMemo(() => catalog?.variables.find((v) => v.id === variable) ?? null, [catalog, variable]);

  // default place: the whole Earth for global data, the data area for test data
  useEffect(() => {
    if (chosen || !varInfo?.data) return;
    if (varInfo.data.kind === "real") setChosen({ region: { place: "preset:globe" }, label: "Whole Earth" });
    else setChosen({ region: { bbox: varInfo.data.bbox.map((x) => Math.round(x * 100) / 100) }, label: "Test box" });
  }, [varInfo, chosen]);

  const run = useCallback(async () => {
    if (!variable || !chosen || !varInfo?.data) return;
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setLoading(true);
    setError(null);
    const body = {
      variable,
      region: chosen.region,
      mode: mode.mode,
      season: mode.mode === "season" ? mode.season : null,
      start_year: mode.start ? Number(mode.start) : null,
      end_year: mode.end ? Number(mode.end) : null,
      cell_map: true,
    };
    try {
      const r = await apiPost<TrendResult>("/analysis/trend", body, c.signal);
      setResult(r);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      if (ctl.current === c) setLoading(false);
    }
    const q = new URLSearchParams({ v: variable, mode: mode.mode });
    if (chosen.region.place) { q.set("place", chosen.region.place); q.set("label", chosen.label); }
    if (chosen.region.bbox) q.set("bbox", chosen.region.bbox.join(","));
    if (mode.mode === "season") q.set("season", mode.season);
    if (mode.start) q.set("start", mode.start);
    if (mode.end) q.set("end", mode.end);
    router.replace(`/?${q.toString()}`, { scroll: false });
  }, [variable, chosen, mode, varInfo, router]);

  useEffect(() => { run(); }, [run]);

  const onBox = useCallback((b: number[]) => {
    setDrawing(false);
    setChosen({ region: { bbox: b } as Region, label: `Box ${b.join(", ")}` });
  }, []);

  const s = result?.series;
  const showTrend = s && s.mode !== "raw";
  const valueLabel = s ? MODE_LABEL[s.mode] ?? "Values" : "";

  return (
    <div>
      <h1>Is this place really changing?</h1>
      <p className="lede">
        Pick <strong>what</strong> (a NASA variable) and <strong>where</strong> (search, a preset, or draw a box). MegavirTrace answers what
        is changing, where, how much, and whether it is significant: two independent tests must agree, after allowing for year-to-year memory.
      </p>

      <div className="filters" role="search" aria-label="Choose what, where and how">
        <VariablePicker catalog={catalog} value={variable} onChange={(v) => {
          setVariable(v);
          const nv = catalog?.variables.find((x) => x.id === v);
          if (nv?.data?.kind !== "real") setChosen(null);
          setMode((m) => ({ ...m, mode: nv?.default_mode ?? "annual" }));
        }} />
        <PlacePicker value={chosen} onChange={(c) => { setChosen(c); setDrawing(false); }} onDrawToggle={() => setDrawing((d) => !d)} drawing={drawing} />
        <ModeControls value={mode} onChange={setMode} />
      </div>

      {varInfo && (
        <details className="card small" style={{ marginBottom: 16 }}>
          <summary>About {varInfo.name.toLowerCase()} ({varInfo.source_badge})</summary>
          <p><strong>What it is:</strong> {varInfo.definition}</p>
          <p><strong>Why it can trend:</strong> {varInfo.why_it_can_trend}</p>
          <p><strong>Caveat:</strong> {varInfo.caveat}</p>
          <p className="muted">
            {varInfo.dataset_info.title}. {varInfo.dataset_info.archive}.{" "}
            {varInfo.data ? `Loaded ${varInfo.data.first_month} to ${varInfo.data.last_month} on a ${varInfo.data.res_deg}° grid (${varInfo.data.kind} data).` : "Not loaded yet."}
          </p>
        </details>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {!result && loading && <p className="spinner-note" role="status">Computing… the first analysis of a region can take a few seconds; repeats are instant.</p>}

      {result && (
        <div style={{ opacity: loading ? 0.55 : 1, transition: "opacity 120ms" }} aria-busy={loading}>
          {loading && <p className="spinner-note" role="status">Updating…</p>}
          <div className="grid-2">
            <div className="stack">
              <VerdictCard verdict={result.verdict} dataKind={result.data.kind} provenance={result.provenance} />
              <section className="card" aria-label="Time series">
                <TrendChart
                  title={`${result.variable.name} — ${result.region.name}${s?.season ? ` (${s.season})` : ""}`}
                  labels={s!.labels}
                  t={s!.t}
                  units={result.units}
                  series={[{ key: "v", label: valueLabel, color: "var(--series-1)", values: s!.plot_values }]}
                  trend={showTrend ? { line: s!.trend_line, slopeLow: result.stats.sen.ci_low, slopeHigh: result.stats.sen.ci_high, label: "Trend (Sen's slope)" } : null}
                  zeroLine={s!.mode === "monthly"}
                />
                {s!.mode === "raw" && <p className="small muted">Raw months are shown as measured; the statistics use monthly anomalies (each month compared with the same month in other years).</p>}
              </section>
            </div>
            <div className="stack">
              <section className="card" aria-label="Where inside the region">
                <h2>Where is it changing?</h2>
                <EarthMap
                  outlines={[{ geometry: result.region.geometry ?? null, bbox: result.region.bbox }]}
                  cells={result.cell_map}
                  variable={result.variable.id}
                  units={result.units}
                  dataArea={result.data.kind !== "real" ? result.data.bbox : null}
                  drawMode={drawing}
                  onBox={onBox}
                  points={globeSites}
                />
              </section>
              <ExplainWithAI id={result.id} />
              <GlobeCard analysisId={result.id} variable={result.variable.id} satelliteLabel={result.variable.source_badge} onSites={setGlobeSites} />
            </div>
          </div>
          <h2 style={{ marginTop: 20 }}>The statistics</h2>
          <StatTiles stats={result.stats} units={result.units} />
          <div style={{ marginTop: 14 }}>
            <Downloads id={result.id} />
          </div>
          <p className="small muted">Computed in {result.compute_ms} ms the first time; stored and reused for this data version.</p>
        </div>
      )}
    </div>
  );
}
