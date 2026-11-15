"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, exportUrl, type Provenance, type Stats, type Verdict } from "@/lib/api";
import { fmt, fmtP, fmtSigned } from "@/lib/format";
import { unitText, useI18n } from "@/lib/i18n";
import Panel, { FullscreenButton } from "@/components/Panel";

const STATUS: Record<string, { icon: string; label: string }> = {
  significant: { icon: "▲▼", label: "Significant trend: both tests agree" },
  not_significant: { icon: "○", label: "No clear trend" },
  tests_disagree: { icon: "◐", label: "Mixed evidence: the tests disagree" },
  not_testable: { icon: "?", label: "Cannot be tested reliably" },
};

export function DataFlag({ kind }: { kind: string }) {
  const { t } = useI18n();
  if (kind === "real") return null;
  return (
    <div className="data-flag" role="note">
      <span aria-hidden="true">⚠</span>
      {kind === "test"
        ? t("TEST DATA — a small development sample of real NASA data, not a final result.")
        : t("SYNTHETIC DATA — made-up numbers for software testing only.")}
    </div>
  );
}

export function VerdictCard({ verdict, dataKind, provenance }: { verdict: Verdict; dataKind: string; provenance?: Provenance }) {
  const { t } = useI18n();
  const s = STATUS[verdict.status] ?? { icon: "•", label: verdict.status };
  return (
    <Panel className="verdict" aria-labelledby="verdict-h">
      <DataFlag kind={dataKind} />
      <span className="status-pill"><span aria-hidden="true">{s.icon}</span>{t(s.label)}</span>
      <h2 id="verdict-h">{verdict.headline}</h2>
      {verdict.sentences.map((x, i) => <p key={i}>{x}</p>)}
      <ul className="caveats" aria-label={t("Caveats")}>
        {verdict.caveats.map((c, i) => <li key={i}>{c}</li>)}
      </ul>
      {provenance && (
        <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
          {t("Source:")} {provenance.source_badge} · {provenance.product}
          {provenance.doi && <> · DOI <a href={`https://doi.org/${provenance.doi}`} rel="noopener noreferrer" target="_blank">{provenance.doi}</a></>}
          {!provenance.doi && provenance.paper_doi && <> · <a href={`https://doi.org/${provenance.paper_doi}`} rel="noopener noreferrer" target="_blank">{t("reference paper")}</a></>}
          {" "}· {t("grid")} {provenance.grid} · {t("data v{v}", { v: provenance.data_version })} · {t("engine")} {provenance.engine_version} · {t("fingerprint")} <code>{provenance.fingerprint.slice(0, 12)}</code>
        </p>
      )}
    </Panel>
  );
}

const PACE: Record<string, string> = { speeding_up: "Speeding up", slowing_down: "Slowing down", changed_direction: "Changed direction" };

type T = (s: string, v?: Record<string, string | number>) => string;

function paceTile(stats: Stats, units: string, t: T) {
  const a = stats.acceleration;
  const label = t("Change of pace");
  if (!a || !a.tested) return { label, value: t("Not tested"), sub: a?.reason ?? t("yearly or seasonal values only") };
  const halves = t("{a} then {b} {units} per decade", { a: fmtSigned((a.slope_early ?? 0) * 10), b: fmtSigned((a.slope_late ?? 0) * 10), units });
  if (a.significant && a.kind) return { label, value: t(PACE[a.kind] ?? a.kind), sub: `${halves} · p ${fmtP(a.p)}` };
  return { label, value: t("Steady"), sub: `${t("no clear change in pace (p {p})", { p: fmtP(a.p) })} · ${halves}` };
}

const pText = (p: number) => `p ${fmtP(p).startsWith("<") ? fmtP(p) : "= " + fmtP(p)}`;

export function StatTiles({ stats, units: unitsRaw }: { stats: Stats; units: string }) {
  const { t, lang } = useI18n();
  const units = unitText(unitsRaw, lang);
  const pd = stats.per_decade;
  const ny = typeof stats.years_needed === "number" ? stats.years_needed : Infinity;
  const tiles = [
    { label: t("Rate (Sen's slope)"), value: `${fmtSigned(pd.sen)} ${units}`, sub: t("per decade · 95% range {a} to {b}", { a: fmtSigned(pd.sen_low), b: fmtSigned(pd.sen_high) }) },
    { label: t("Least-squares rate"), value: `${fmtSigned(pd.ols)} ${units}`, sub: t("per decade · 95% range {a} to {b}", { a: fmtSigned(pd.ols_low), b: fmtSigned(pd.ols_high) }) },
    { label: t("Mann–Kendall test"), value: pText(stats.mk.p), sub: `${stats.seasonal_test ? t("seasonal test, ") : ""}${t("τ = {tau}, corrected for memory", { tau: fmt(stats.mk.tau, 2) })}` },
    { label: t("Least-squares test"), value: pText(stats.ols.p), sub: t("t-test with {neff} effective values of {n}", { neff: fmt(stats.ols.n_eff, 2), n: stats.n }) },
    { label: t("Year-to-year memory"), value: `r₁ = ${fmt(stats.ols.r1, 2)}`, sub: t("lag-1 autocorrelation, small-sample corrected (raw {raw})", { raw: fmt(stats.ols.r1_raw, 2) }) },
    { label: t("Size against the noise"), value: t(stats.effect_label), sub: t("trend over the record ÷ scatter = {r}", { r: fmt(stats.effect_ratio, 2) }) },
    { label: t("Years needed to detect"), value: Number.isFinite(ny) ? t("{n} years", { n: Math.ceil(ny) }) : "—", sub: Number(stats.years_more) > 0 ? t("{n} more than this record", { n: String(stats.years_more) }) : t("this record is long enough for a trend this size") },
    { label: t("Robustness"), value: stats.robustness.fragile ? t("Fragile") : t("Holds"), sub: stats.robustness.fragile ? t("changes direction in a half or without one year") : t("both halves, no end years, any one year left out") },
    paceTile(stats, units, t),
  ];
  return (
    <section aria-label={t("Statistics")}>
      <div className="tiles">
        {tiles.map((x) => (
          <div className="tile" key={x.label}>
            <div className="label">{x.label}</div>
            <div className="value">{x.value}</div>
            <div className="sub">{x.sub}</div>
          </div>
        ))}
      </div>
      {(stats.unusual.length > 0 || stats.turning?.preferred) && (
        <details style={{ marginTop: 10 }}>
          <summary>{t("Extra clues (exploratory)")}</summary>
          <ul className="small">
            {stats.turning?.preferred && (
              <li>{t("A turning point near {year}: {before} then {after} {units} per decade.", { year: String(Math.floor(stats.turning.at)), before: fmtSigned(stats.turning.slope_before * 10), after: fmtSigned(stats.turning.slope_after * 10), units })}</li>
            )}
            {stats.unusual.map((u) => (
              <li key={u.label}>{t("Unusual: {label}, {dep} {units} from the trend line ({sd} standard deviations).", { label: u.label, dep: fmtSigned(u.departure, 2), units, sd: fmt(u.sd_units, 2) })}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function Downloads({ id }: { id: string }) {
  const { t } = useI18n();
  const items = [
    ["csv", "CSV"],
    ["xlsx", "Excel"],
    ["pdf", "PDF"],
    ["ipynb", t("Notebook (recomputes every number)")],
  ];
  return (
    <section aria-label="Downloads" className="row small">
      <strong>{t("Take it away:")}</strong>
      {items.map(([f, l]) => <a key={f} className="button" href={exportUrl(id, f)} download>{l}</a>)}
      <a className="button" href={`/embed/${id}`} target="_blank" rel="noopener">{t("Embeddable card")}</a>
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
  const { lang, t } = useI18n();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<AiReply | null>(null);
  useEffect(() => {
    apiGet<{ enabled: boolean }>("/ai/status").then((s) => setEnabled(s.enabled)).catch(() => setEnabled(false));
  }, []);
  useEffect(() => setReply(null), [id]);
  if (!enabled) return null;
  return (
    <Panel aria-label="AI explanation">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{t("Ask the AI scientist to explain this result")}</strong>
        {/* the full-screen switch sits in this row, so the card shows none in its corner over the button */}
        <span className="row" style={{ gap: 8 }}>
          <button type="button" disabled={busy} onClick={async () => {
            setBusy(true);
            try { setReply(await apiPost<AiReply>("/ai/explain", { analysis_id: id, lang })); } catch (e) { setReply({ mode: "error", reason: String(e) }); }
            setBusy(false);
          }}>{busy ? t("Thinking…") : t("Explain")}</button>
          <FullscreenButton />
        </span>
      </div>
      {reply?.mode === "answered" && reply.answer && (
        <div aria-live="polite">
          <h3 style={{ marginTop: 10 }}>{reply.answer.headline}</h3>
          {reply.answer.explanation.split(/\n+/).map((p, i) => <p key={i}>{p}</p>)}
          <p className="small muted">Checked: all {reply.check?.numbers_checked ?? 0} numbers match the computed result. The AI explains; it never computes.</p>
        </div>
      )}
      {reply && reply.mode !== "answered" && <p className="small muted" aria-live="polite">{reply.reason}</p>}
    </Panel>
  );
}
