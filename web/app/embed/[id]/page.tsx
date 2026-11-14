"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import TrendChart from "@/components/TrendChart";
import { apiGet, type TrendResult } from "@/lib/api";

// Embeddable trend card (FR17): frameable on any site, carries its source and checks.
export default function EmbedCard() {
  const { id } = useParams<{ id: string }>();
  const [r, setR] = useState<TrendResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { apiGet<TrendResult>(`/reports/${id}`).then(setR).catch((e) => setErr(e.message)); }, [id]);

  if (err) return <div className="embed-card card">This result is not available ({err}).</div>;
  if (!r) return <div className="embed-card card">Loading…</div>;
  if (r.kind !== "trend") return <div className="embed-card card">{(r as unknown as { verdict: { headline: string } }).verdict.headline}</div>;
  const s = r.series;
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const iframe = `<iframe src="${origin}/embed/${r.id}" width="560" height="460" style="border:0" title="${r.verdict.headline.replace(/"/g, "&quot;")}"></iframe>`;
  return (
    <div className="embed-card card" style={{ maxWidth: 640, margin: "0 auto" }}>
      {r.data.kind !== "real" && <div className="data-flag" role="note">⚠ {r.data.kind === "test" ? "TEST DATA — not a final result" : "SYNTHETIC DATA — for software testing"}</div>}
      <h1 style={{ fontSize: "1.15rem" }}>{r.verdict.headline}</h1>
      <p className="small" style={{ margin: "4px 0 8px" }}>{r.verdict.sentences[1] ?? r.verdict.sentences[0]}</p>
      <TrendChart
        title={`${r.variable.name} — ${r.region.name}`}
        labels={s.labels}
        t={s.t}
        units={r.units}
        series={[{ key: "v", label: "Values", color: "var(--series-1)", values: s.plot_values }]}
        trend={s.mode !== "raw" ? { line: s.trend_line, slopeLow: r.stats.sen.ci_low, slopeHigh: r.stats.sen.ci_high, label: "Trend (Sen's slope)" } : null}
        height={220}
      />
      <p className="small muted" style={{ margin: "6px 0 0" }}>
        {r.verdict.caveats[r.data.kind !== "real" ? 1 : 0]} Source: {r.provenance.source_badge} ({r.provenance.product}
        {r.provenance.doi ? `, doi:${r.provenance.doi}` : ""}). Checked by two independent tests corrected for year-to-year memory · fingerprint{" "}
        <code>{r.provenance.fingerprint.slice(0, 12)}</code> ·{" "}
        <a href={`${origin}/?v=${r.variable.id}${r.region.id ? `&place=${encodeURIComponent(r.region.id)}` : `&bbox=${r.region.bbox.join(",")}`}`} target="_blank" rel="noopener">Open in MegavirTrace</a>
      </p>
      <details className="small" style={{ marginTop: 8 }}>
        <summary>Embed this card</summary>
        <textarea readOnly value={iframe} aria-label="Embed code" style={{ fontSize: "0.8rem" }} />
      </details>
    </div>
  );
}
