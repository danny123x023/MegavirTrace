"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, exportUrl, type Provenance, type Stats, type Verdict } from "@/lib/api";
import { fmt, fmtP, fmtSigned } from "@/lib/format";

const STATUS: Record<string, { icon: string; label: string }> = {
  significant: { icon: "▲▼", label: "Significant trend: both tests agree" },
  not_significant: { icon: "○", label: "No clear trend" },
  tests_disagree: { icon: "◐", label: "Mixed evidence: the tests disagree" },
  not_testable: { icon: "?", label: "Cannot be tested reliably" },
};

export function DataFlag({ kind }: { kind: string }) {
  if (kind === "real") return null;
  return (
    <div className="data-flag" role="note">
      <span aria-hidden="true">⚠</span>
      {kind === "test"
        ? "TEST DATA — a small development sample of real NASA data, not a final result."
        : "SYNTHETIC DATA — made-up numbers for software testing only."}
    </div>
  );
}

export function VerdictCard({ verdict, dataKind, provenance }: { verdict: Verdict; dataKind: string; provenance?: Provenance }) {
  const s = STATUS[verdict.status] ?? { icon: "•", label: verdict.status };
  return (
    <section className="card verdict" aria-labelledby="verdict-h">
      <DataFlag kind={dataKind} />
      <span className="status-pill"><span aria-hidden="true">{s.icon}</span>{s.label}</span>
      <h2 id="verdict-h">{verdict.headline}</h2>
      {verdict.sentences.map((x, i) => <p key={i}>{x}</p>)}
      <ul className="caveats" aria-label="Caveats">
        {verdict.caveats.map((c, i) => <li key={i}>{c}</li>)}
      </ul>
      {provenance && (
        <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
          Source: {provenance.source_badge} · {provenance.product}
          {provenance.doi && <> · DOI <a href={`https://doi.org/${provenance.doi}`} rel="noopener noreferrer" target="_blank">{provenance.doi}</a></>}
          {!provenance.doi && provenance.paper_doi && <> · <a href={`https://doi.org/${provenance.paper_doi}`} rel="noopener noreferrer" target="_blank">reference paper</a></>}
          {" "}· grid {provenance.grid} · data v{provenance.data_version} · engine {provenance.engine_version} · fingerprint <code>{provenance.fingerprint.slice(0, 12)}</code>
        </p>
      )}
    </section>
  );
}

export function StatTiles({ stats, units }: { stats: Stats; units: string }) {
  const pd = stats.per_decade;
  const ny = typeof stats.years_needed === "number" ? stats.years_needed : Infinity;
  const tiles = [
    { label: "Rate (Sen's slope)", value: `${fmtSigned(pd.sen)} ${units}`, sub: `per decade · 95% range ${fmtSigned(pd.sen_low)} to ${fmtSigned(pd.sen_high)}` },
    { label: "Least-squares rate", value: `${fmtSigned(pd.ols)} ${units}`, sub: `per decade · 95% range ${fmtSigned(pd.ols_low)} to ${fmtSigned(pd.ols_high)}` },
    { label: "Mann–Kendall test", value: `p ${fmtP(stats.mk.p).startsWith("<") ? fmtP(stats.mk.p) : "= " + fmtP(stats.mk.p)}`, sub: `${stats.seasonal_test ? "seasonal test, " : ""}τ = ${fmt(stats.mk.tau, 2)}, corrected for memory` },
    { label: "Least-squares test", value: `p ${fmtP(stats.ols.p).startsWith("<") ? fmtP(stats.ols.p) : "= " + fmtP(stats.ols.p)}`, sub: `t-test with ${fmt(stats.ols.n_eff, 2)} effective values of ${stats.n}` },
    { label: "Year-to-year memory", value: `r₁ = ${fmt(stats.ols.r1, 2)}`, sub: `lag-1 autocorrelation, small-sample corrected (raw ${fmt(stats.ols.r1_raw, 2)})` },
    { label: "Size against the noise", value: stats.effect_label, sub: `trend over the record ÷ scatter = ${fmt(stats.effect_ratio, 2)}` },
    { label: "Years needed to detect", value: Number.isFinite(ny) ? `${Math.ceil(ny)} years` : "—", sub: Number(stats.years_more) > 0 ? `${stats.years_more} more than this record` : "this record is long enough for a trend this size" },
    { label: "Robustness", value: stats.robustness.fragile ? "Fragile" : "Holds", sub: stats.robustness.fragile ? "changes direction in a half or without one year" : "both halves, no end years, any one year left out" },
  ];
  return (
    <section aria-label="Statistics">
      <div className="tiles">
        {tiles.map((t) => (
          <div className="tile" key={t.label}>
            <div className="label">{t.label}</div>
            <div className="value">{t.value}</div>
            <div className="sub">{t.sub}</div>
          </div>
        ))}
      </div>
      {(stats.unusual.length > 0 || stats.turning?.preferred) && (
        <details style={{ marginTop: 10 }}>
          <summary>Extra clues (exploratory)</summary>
          <ul className="small">
            {stats.turning?.preferred && (
              <li>A turning point near {Math.floor(stats.turning.at)}: {fmtSigned(stats.turning.slope_before * 10)} then {fmtSigned(stats.turning.slope_after * 10)} {units} per decade.</li>
            )}
            {stats.unusual.map((u) => (
              <li key={u.label}>Unusual: {u.label}, {fmtSigned(u.departure, 2)} {units} from the trend line ({fmt(u.sd_units, 2)} standard deviations).</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function Downloads({ id }: { id: string }) {
  const items = [
    ["csv", "CSV"],
    ["xlsx", "Excel"],
    ["pdf", "PDF"],
    ["ipynb", "Notebook (recomputes every number)"],
  ];
  return (
    <section aria-label="Downloads" className="row small">
      <strong>Take it away:</strong>
      {items.map(([f, l]) => <a key={f} className="button" href={exportUrl(id, f)} download>{l}</a>)}
      <a className="button" href={`/embed/${id}`} target="_blank" rel="noopener">Embeddable card</a>
    </section>
  );
}

type AiReply = {
  mode: string;
  reason?: string;
  answer?: { headline: string; explanation: string; follow_up_questions?: string[] } | null;
  template_verdicts?: { headline: string; sentences: string[] }[];
  check?: { numbers_checked: number };
};

export function ExplainWithAI({ id }: { id: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<AiReply | null>(null);
  useEffect(() => {
    apiGet<{ enabled: boolean }>("/ai/status").then((s) => setEnabled(s.enabled)).catch(() => setEnabled(false));
  }, []);
  useEffect(() => setReply(null), [id]);
  if (!enabled) return null;
  return (
    <section className="card" aria-label="AI explanation">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>Ask the AI scientist to explain this result</strong>
        <button type="button" disabled={busy} onClick={async () => {
          setBusy(true);
          try { setReply(await apiPost<AiReply>("/ai/explain", { analysis_id: id })); } catch (e) { setReply({ mode: "error", reason: String(e) }); }
          setBusy(false);
        }}>{busy ? "Thinking…" : "Explain"}</button>
      </div>
      {reply?.mode === "answered" && reply.answer && (
        <div aria-live="polite">
          <h3 style={{ marginTop: 10 }}>{reply.answer.headline}</h3>
          {reply.answer.explanation.split(/\n+/).map((p, i) => <p key={i}>{p}</p>)}
          <p className="small muted">Checked: all {reply.check?.numbers_checked ?? 0} numbers match the computed result. The AI explains; it never computes.</p>
        </div>
      )}
      {reply && reply.mode !== "answered" && <p className="small muted" aria-live="polite">{reply.reason}</p>}
    </section>
  );
}
