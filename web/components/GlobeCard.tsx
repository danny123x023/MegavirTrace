"use client";

import { useEffect, useState } from "react";
import TrendChart from "@/components/TrendChart";
import { apiGet } from "@/lib/api";
import { fmt } from "@/lib/format";
import Panel from "@/components/Panel";
import { useI18n } from "@/lib/i18n";

export type GlobeSite = { id: number; name: string; lat: number; lon: number; n_months: number };

type GlobeContext = {
  label: string;
  units: string;
  period: string[];
  globe: { months: string[]; values: number[]; n_sites: number[] };
  sites: GlobeSite[];
  n_sites: number;
  n_records: number;
  comparison: { months: string[]; globe_anomaly: (number | null)[]; satellite_anomaly: (number | null)[]; n_shared: number; anomaly_correlation: number | null };
  caveats: string[];
  source: string;
};

const PAIRED = new Set(["air_temp", "temp_change", "daily_high", "nightly_low", "rainfall"]);

export default function GlobeCard({ analysisId, variable, satelliteLabel, onSites }: {
  analysisId: string;
  variable: string;
  satelliteLabel: string;
  onSites?: (s: GlobeSite[]) => void;
}) {
  const { t } = useI18n();
  const [data, setData] = useState<GlobeContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setData(null); setError(null); onSites?.([]); }, [analysisId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!PAIRED.has(variable)) return null;

  async function load() {
    setBusy(true);
    setError(null);
    try {
      const d = await apiGet<GlobeContext>("/context/globe", { analysis_id: analysisId });
      setData(d);
      onSites?.(d.sites);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  const c = data?.comparison;
  const tt = c?.months.map((m) => Number(m.slice(0, 4)) + (Number(m.slice(5, 7)) - 0.5) / 12) ?? [];

  return (
    <Panel aria-labelledby="globe-h">
      <h2 id="globe-h">{t("Ground observations: NASA GLOBE")}</h2>
      <p className="small muted" style={{ marginTop: 0 }}>
        {t("Measurements by schools and volunteers in the GLOBE Program, for the same place, shown beside the satellite series as monthly anomalies (each month compared with the same month in other years). Context only: they are not used in the trend tests.")}
      </p>
      {!data && (
        <button type="button" onClick={load} disabled={busy}>
          {busy ? t("Fetching GLOBE observations… (the first time can take a minute)") : t("Show GLOBE ground observations")}
        </button>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {data && c && (
        <div className="stack" style={{ gap: 10 }}>
          {c.n_shared === 0 ? (
            <p>{t("No GLOBE observations overlap this record here ({r} records found, {s} sites).", { r: String(data.n_records), s: String(data.n_sites) })}</p>
          ) : (
            <>
              <div className="tiles">
                <div className="tile"><div className="label">{t("Move together")}</div><div className="value">{c.anomaly_correlation === null ? "—" : `r = ${fmt(c.anomaly_correlation, 2)}`}</div><div className="sub">{t("monthly anomalies, {n} shared months", { n: String(c.n_shared) })}</div></div>
                <div className="tile"><div className="label">{t("GLOBE sites")}</div><div className="value">{data.n_sites}</div><div className="sub">{t("{n} readings, {a}–{b}", { n: fmt(data.n_records, 6), a: data.period[0].slice(0, 4), b: data.period[1].slice(0, 4) })}</div></div>
              </div>
              <TrendChart
                title={t("Monthly anomalies: {a} and {b}", { a: satelliteLabel, b: data.label })}
                labels={c.months}
                t={tt}
                units={data.units === "mm/month" ? "mm/month" : "°C"}
                series={[
                  { key: "sat", label: satelliteLabel, color: "var(--series-1)", values: c.satellite_anomaly, markers: false },
                  { key: "globe", label: t("GLOBE ground observations"), color: "var(--series-2)", values: c.globe_anomaly, markers: false },
                ]}
                zeroLine
                height={240}
              />
            </>
          )}
          <details className="small">
            <summary>{t("Sites ({n})", { n: String(data.n_sites) })}</summary>
            <ul>
              {data.sites.slice(0, 30).map((s) => (
                <li key={s.id}>{t("{name} ({lat}°, {lon}°): {n} months", { name: s.name, lat: fmt(s.lat, 3), lon: fmt(s.lon, 3), n: String(s.n_months) })}</li>
              ))}
            </ul>
          </details>
          <ul className="caveats">{data.caveats.map((x) => <li key={x}>{x}</li>)}</ul>
          <p className="small muted" style={{ margin: 0 }}>{t("Source: {s}. Sites are marked on the map.", { s: data.source })}</p>
        </div>
      )}
    </Panel>
  );
}
