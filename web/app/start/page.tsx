"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { type Chosen, PlacePicker } from "@/components/Pickers";
import { apiGet, apiPost, type Catalog } from "@/lib/api";
import { fmt, fmtSigned } from "@/lib/format";

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

type ScanRow = {
  variable: string; name: string; theme?: string; analysis_id?: string; per_decade?: number; units?: string; direction?: string;
  significant?: boolean; q?: number; passes_fdr?: boolean; headline?: string; data_kind?: string; error?: string;
};

export default function StartPage() {
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
      <h1>Where do I start?</h1>
      <p className="lede">Answer two quick questions and we suggest variables worth checking. Or pick a place and let MegavirTrace test every variable for you.</p>

      <div className="grid-2">
        <section className="card" aria-labelledby="q-h">
          <h2 id="q-h">1. What kind of place?</h2>
          <div className="chip-list" role="group" aria-label="Kind of place">
            {Object.entries(PLACE_TYPES).map(([k, v]) => (
              <button key={k} type="button" className="chip" aria-pressed={ptype === k} onClick={() => setPtype(k)}>{v.label}</button>
            ))}
          </div>
          <h2 style={{ marginTop: 16 }}>2. What are you curious about?</h2>
          <div className="chip-list" role="group" aria-label="Curiosity">
            {Object.entries(CURIOSITY).map(([k, v]) => (
              <button key={k} type="button" className="chip" aria-pressed={curious === k} onClick={() => setCurious(curious === k ? null : k)}>{v.label}</button>
            ))}
          </div>
          <h2 style={{ marginTop: 16 }}>Suggested variables</h2>
          <ul className="prose">
            {suggestions.map((v) => (
              <li key={v.id}>
                <strong>{v.name}</strong> ({v.source_badge}) — {v.why_it_can_trend}{" "}
                {v.data ? <Link href={`/?v=${v.id}${placeQuery}`}>Explore it</Link> : <span className="muted">(not loaded yet)</span>}
                {v.data && v.data.kind !== "real" && <span className="muted small"> · {v.data.kind} data only</span>}
              </li>
            ))}
          </ul>
        </section>

        <section className="card" aria-labelledby="scan-h">
          <h2 id="scan-h">What is changing here?</h2>
          <p className="muted small">
            Tests every loaded variable for one place. Testing many variables at once raises the chance of a false alarm, so the results use
            false-discovery control across the variables (Benjamini–Hochberg, q ≤ 0.05).
          </p>
          <PlacePicker label="Place" value={place} onChange={(c) => { setPlace(c); setScan(null); }} />
          <div style={{ marginTop: 10 }}>
            <button type="button" className="primary" disabled={!place || busy} onClick={async () => {
              if (!place) return;
              setBusy(true); setError(null);
              try { setScan(await apiPost("/analysis/scan", { region: place.region })); } catch (e) { setError((e as Error).message); }
              setBusy(false);
            }}>{busy ? "Testing every variable…" : "Test every variable"}</button>
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          {scan && (
            <div style={{ marginTop: 12 }} aria-live="polite">
              <h3>{scan.region.name}</h3>
              <div className="table-scroll">
                <table className="data">
                  <thead><tr><th scope="col">Variable</th><th scope="col">Trend per decade</th><th scope="col">q</th><th scope="col">Result</th></tr></thead>
                  <tbody>
                    {scan.results.map((r) => (
                      <tr key={r.variable}>
                        <td>{r.analysis_id ? <Link href={`/?v=${r.variable}${placeQuery}`}>{r.name}</Link> : r.name}{r.data_kind && r.data_kind !== "real" ? ` (${r.data_kind})` : ""}</td>
                        <td>{r.per_decade !== undefined ? `${fmtSigned(r.per_decade)} ${r.units}` : "—"}</td>
                        <td>{r.q !== undefined ? fmt(r.q, 2) : "—"}</td>
                        <td style={{ textAlign: "left" }}>{r.error ? <span className="muted">{r.error}</span> : r.passes_fdr ? "Changing (passes)" : r.significant ? "Significant alone, not after control" : "No clear trend"}</td>
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
    </div>
  );
}
