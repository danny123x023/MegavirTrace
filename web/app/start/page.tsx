"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { type Chosen, PlacePicker } from "@/components/Pickers";
import { apiGet, apiPost, type Catalog } from "@/lib/api";
import { fmt, fmtSigned } from "@/lib/format";
import { useI18n, varText } from "@/lib/i18n";

const PLACE_TYPES: Record<string, { label: string; vars: string[] }> = {
  city: { label: "A city", vars: ["no2", "nightly_low", "daily_high", "downpour", "air_temp"] },
  farm: { label: "Farmland", vars: ["soil_moisture", "rainfall", "ndvi", "evapotranspiration", "daily_high"] },
  coast: { label: "A coast or island", vars: ["sea_level", "sea_surface_temp", "downpour", "rainfall"] },
  mountain: { label: "Mountains or ice", vars: ["air_temp", "land_water", "ground_temp", "temp_change"] },
  dry: { label: "A dry place or desert", vars: ["rainfall", "topsoil_moisture", "ground_temp", "land_water", "ndvi"] },
  forest: { label: "A forest", vars: ["ndvi", "fire_carbon", "rainfall", "daily_high"] },
  ocean: { label: "Open ocean", vars: ["sea_surface_temp", "sea_level"] },
  anywhere: { label: "Anywhere", vars: ["temp_change", "air_temp", "rainfall"] },
};

const CURIOSITY: Record<string, { label: string; themes: string[] }> = {
  heat: { label: "Heat", themes: ["Heat"] },
  water: { label: "Rain and water", themes: ["Water cycle", "Soil and land water"] },
  air: { label: "Air we breathe", themes: ["Air quality"] },
  plants: { label: "Plants and fire", themes: ["Vegetation", "Fire"] },
  sea: { label: "The sea", themes: ["Ocean"] },
};

// simple line icons, one per kind of place
const PATHS: Record<string, string> = {
  city: "M4 21V7l6-3v17M10 21V9l10 3v9M3 21h18M7 9v.01M7 12v.01M7 15v.01M14 14v.01M17 14v.01M14 17v.01M17 17v.01",
  farm: "M12 21V10M12 10c0-3 2-5 5-5 0 3-2 5-5 5ZM12 14c0-3-2-5-5-5 0 3 2 5 5 5ZM12 18c0-2.5 2-4 4.5-4 0 2.5-2 4-4.5 4Z",
  coast: "M3 17c1.5 1.3 3 1.3 4.5 0s3-1.3 4.5 0 3 1.3 4.5 0 3-1.3 4.5 0M3 12c1.5 1.3 3 1.3 4.5 0s3-1.3 4.5 0M14 4l4 4-4 4",
  mountain: "M3 20l6.5-12 4 7 2.5-4L21 20ZM8 12.5l1.5 1.5 1.5-1.5",
  dry: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  forest: "M12 3l5 7h-3l4 6H6l4-6H7ZM12 16v5",
  ocean: "M3 8c1.5 1.3 3 1.3 4.5 0s3-1.3 4.5 0 3 1.3 4.5 0 3-1.3 4.5 0M3 13c1.5 1.3 3 1.3 4.5 0s3-1.3 4.5 0 3 1.3 4.5 0 3-1.3 4.5 0M3 18c1.5 1.3 3 1.3 4.5 0s3-1.3 4.5 0 3 1.3 4.5 0 3-1.3 4.5 0",
  anywhere: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM3 12h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9M12 3c-2.5 2.5-3.5 5.5-3.5 9s1 6.5 3.5 9",
};

function PlaceIcon({ kind }: { kind: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[kind]} />
    </svg>
  );
}

type ScanRow = {
  variable: string; name: string; theme?: string; analysis_id?: string; per_decade?: number; units?: string; direction?: string;
  significant?: boolean; q?: number; passes_fdr?: boolean; headline?: string; data_kind?: string; error?: string;
};

export default function StartPage() {
  const { lang, t } = useI18n();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [ptype, setPtype] = useState("anywhere");
  const [curious, setCurious] = useState<string | null>(null);
  const [place, setPlace] = useState<Chosen | null>(null);
  const [scan, setScan] = useState<{ region: { name: string }; results: ScanRow[]; note: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { apiGet<Catalog>("/variables").then(setCatalog).catch((e) => setError(e.message)); }, []);

  const suggestions = useMemo(() => {
    if (!catalog) return [];
    let ids = PLACE_TYPES[ptype].vars;
    if (curious) {
      const themes = CURIOSITY[curious].themes;
      const byTheme = catalog.variables.filter((v) => themes.includes(v.theme)).map((v) => v.id);
      const both = ids.filter((id) => byTheme.includes(id));
      ids = both.length ? both : byTheme;
    }
    return ids.map((id) => catalog.variables.find((v) => v.id === id)).filter((v): v is NonNullable<typeof v> => !!v);
  }, [catalog, ptype, curious]);

  const placeQuery = place?.region.place ? `&place=${encodeURIComponent(place.region.place)}&label=${encodeURIComponent(place.label)}` : place?.region.bbox ? `&bbox=${place.region.bbox.join(",")}` : "";

  return (
    <div>
      <h1>{t("Where do I start?")}</h1>
      <p className="lede">{t("Answer two quick questions and we suggest what to investigate. Or pick a place and let MegavirTrace test every variable for you.")}</p>

      <section aria-labelledby="q1">
        <h2 id="q1" className="step-title">{t("1. What kind of place are you curious about?")}</h2>
        <div className="choice-grid" role="group" aria-labelledby="q1">
          {Object.entries(PLACE_TYPES).map(([k, v]) => (
            <button key={k} type="button" className="choice-card" aria-pressed={ptype === k} onClick={() => setPtype(k)}>
              <span className="choice-icon"><PlaceIcon kind={k} /></span>
              <span className="choice-title">{t(v.label)}</span>
              <span className="choice-meta">{t("{n} variables to check", { n: v.vars.length })}</span>
            </button>
          ))}
        </div>
      </section>

      <section aria-labelledby="q2">
        <h2 id="q2" className="step-title">{t("2. What are you curious about?")}</h2>
        <div className="chip-list" role="group" aria-labelledby="q2">
          {Object.entries(CURIOSITY).map(([k, v]) => (
            <button key={k} type="button" className="chip" aria-pressed={curious === k} onClick={() => setCurious(curious === k ? null : k)}>{t(v.label)}</button>
          ))}
        </div>
        <p className="hint">
          {t("Pick one to narrow the suggestions, or leave it to see them all.")} {t("Somewhere specific?")}{" "}
          <Link href="/">{t("Explore")}</Link> {t("searches every city, country and state, or lets you draw a box on the map.")}
        </p>
      </section>

      <section aria-labelledby="q3">
        <h2 id="q3" className="step-title">{t("3. What could be changing there?")}</h2>
        <div className="suggest-grid">
          {suggestions.map((v) => (
            <article key={v.id} className="card suggest-card">
              <h3>{varText(v, lang)} <span className="badge">{v.source_badge}</span></h3>
              <p>{varText(v, lang, "why_it_can_trend")}</p>
              <div className="row small">
                {v.data ? (
                  <Link className="card-link" href={`/?v=${v.id}${placeQuery}`}>{t("Explore it")} →</Link>
                ) : (
                  <span className="muted">{t("Not loaded yet")}</span>
                )}
                {v.data && v.data.kind !== "real" && <span className="muted">· {t("test data only")}</span>}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="scan-h" style={{ marginTop: 36 }}>
        <h2 id="scan-h">{t("What is changing here?")}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          {t("Tests every loaded variable for one place. Testing many variables at once raises the chance of a false alarm, so the results use false-discovery control across the variables (Benjamini–Hochberg, q ≤ 0.05).")}
        </p>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <PlacePicker label={t("Place")} value={place} onChange={(c) => { setPlace(c); setScan(null); }} />
          <button type="button" className="primary" disabled={!place || busy} onClick={async () => {
            if (!place) return;
            setBusy(true); setError(null);
            try { setScan(await apiPost("/analysis/scan", { region: place.region, lang })); } catch (e) { setError((e as Error).message); }
            setBusy(false);
          }}>{busy ? t("Testing every variable…") : t("Test every variable")}</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {scan && (
          <div style={{ marginTop: 14 }} aria-live="polite">
            <h3>{scan.region.name}</h3>
            <div className="table-scroll">
              <table className="data">
                <thead><tr><th scope="col">{t("Variable")}</th><th scope="col">{t("Trend per decade")}</th><th scope="col">q</th><th scope="col">{t("Result")}</th></tr></thead>
                <tbody>
                  {scan.results.map((r) => (
                    <tr key={r.variable}>
                      <td>{r.analysis_id ? <Link href={`/?v=${r.variable}${placeQuery}`}>{r.name}</Link> : r.name}{r.data_kind && r.data_kind !== "real" ? ` (${r.data_kind})` : ""}</td>
                      <td>{r.per_decade !== undefined ? `${fmtSigned(r.per_decade)} ${r.units}` : "—"}</td>
                      <td>{r.q !== undefined ? fmt(r.q, 2) : "—"}</td>
                      <td style={{ textAlign: "left" }}>{r.error ? <span className="muted">{r.error}</span> : r.passes_fdr ? t("Changing (passes)") : r.significant ? t("Significant alone, not after control") : t("No clear trend")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted">{scan.note}</p>
          </div>
        )}
      </section>
    </div>
  );
}
