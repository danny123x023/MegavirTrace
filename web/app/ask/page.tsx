"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { fmtP, fmtSigned } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

type Card = {
  analysis_id: string; kind: string;
  card: {
    variable: string; region?: string; region_a?: string; region_b?: string; units: string; period?: string;
    per_decade?: { sen: number; sen_low: number; sen_high: number }; p_mann_kendall?: number; p_least_squares?: number;
    significant: boolean; difference_per_decade?: number; p?: number; verdict: string; data_kind: string;
  };
};
type Reply = {
  mode: "answered" | "fallback" | "unavailable" | "no_analysis" | "error";
  reason?: string;
  answer?: { headline: string; explanation: string; follow_up_questions?: string[] } | null;
  analyses?: Card[];
  template_verdicts?: { analysis_id: string; headline: string; sentences: string[]; caveats: string[] }[];
  check?: { numbers_checked: number };
  suggestions?: string[];
};
type Turn = { q: string; r: Reply };

const EXAMPLES = [
  "Is the whole Earth really warming, and since when?",
  "Is Siberia warming faster than the North Atlantic?",
  "What is changing in the Gulf Coast test box?",
];

export default function AskPage() {
  const { lang, t } = useI18n();
  const [status, setStatus] = useState<{ enabled: boolean; provider: string; model: string | null } | null>(null);
  const [q, setQ] = useState("");
  const [tutor, setTutor] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { apiGet<typeof status>("/ai/status").then(setStatus).catch(() => setStatus({ enabled: false, provider: "none", model: null })); }, []);

  async function ask(question: string) {
    if (question.trim().length < 3) return;
    setBusy(true);
    const history = turns.flatMap((t) => [
      { role: "user", content: t.q },
      ...(t.r.answer ? [{ role: "assistant", content: `${t.r.answer.headline}\n${t.r.answer.explanation}` }] : []),
    ]).slice(-6);
    let r: Reply;
    try {
      r = await apiPost<Reply>("/ai/ask", { question, mode: tutor ? "tutor" : "explain", history, lang });
    } catch (e) {
      r = { mode: "error", reason: (e as Error).message };
    }
    setTurns((t) => [...t, { q: question, r }]);
    setQ("");
    setBusy(false);
  }

  return (
    <div>
      <h1>{t("Ask the AI scientist")}</h1>
      <p className="lede">
        Ask in plain words. The AI turns your question into analyses run by MegavirTrace&apos;s engine, then explains them. It never computes:
        every number it writes is checked against the stored results, and if anything does not match you see the computed verdict instead.
      </p>

      {status && !status.enabled && (
        <p className="error" role="note">
          The AI scientist is switched off on this server (no AI service is configured). Everything else works without it:{" "}
          <Link href="/">explore</Link> or <Link href="/compare">compare</Link> any place.
        </p>
      )}

      <section className="card" aria-label="Your question">
        <label htmlFor="q" className="label" style={{ fontWeight: 600 }}>Your question</label>
        <textarea id="q" value={q} maxLength={600} onChange={(e) => setQ(e.target.value)} placeholder="For example: Is rainfall in the Sahel changing?" />
        <div className="row" style={{ marginTop: 8, justifyContent: "space-between" }}>
          <label className="row small">
            <input type="checkbox" checked={tutor} onChange={(e) => setTutor(e.target.checked)} />
            Tutor mode: guide me with questions instead of explaining
          </label>
          <button type="button" className="primary" disabled={busy || !status?.enabled || q.trim().length < 3} onClick={() => ask(q)}>
            {busy ? t("Running the analyses…") : t("Ask")}
          </button>
        </div>
        <div className="chip-list" style={{ marginTop: 10 }}>
          {EXAMPLES.map((e) => <button key={e} type="button" className="chip" disabled={!status?.enabled || busy} onClick={() => ask(e)}>{e}</button>)}
        </div>
      </section>

      <div className="stack" style={{ marginTop: 16 }} aria-live="polite">
        {turns.map((t, i) => (
          <section key={i} className="card" aria-label={`Answer ${i + 1}`}>
            <p className="muted small" style={{ marginTop: 0 }}>You asked: {t.q}</p>
            {t.r.mode === "answered" && t.r.answer && (
              <>
                <h2>{t.r.answer.headline}</h2>
                {t.r.answer.explanation.split(/\n+/).map((p, j) => <p key={j}>{p}</p>)}
                <p className="small muted">✓ Number check passed: {t.r.check?.numbers_checked ?? 0} numbers match the stored analyses.</p>
                {!!t.r.answer.follow_up_questions?.length && (
                  <div className="chip-list">
                    {t.r.answer.follow_up_questions.map((f) => <button key={f} type="button" className="chip" onClick={() => ask(f)}>{f}</button>)}
                  </div>
                )}
              </>
            )}
            {t.r.mode !== "answered" && <p><strong>{t.r.reason}</strong></p>}
            {t.r.template_verdicts?.map((v) => (
              <div key={v.analysis_id}>
                <h3>{v.headline}</h3>
                {v.sentences.map((s, j) => <p key={j}>{s}</p>)}
              </div>
            ))}
            {!!t.r.analyses?.length && (
              <div className="tiles" style={{ marginTop: 10 }}>
                {t.r.analyses.map((a) => (
                  <div className="tile" key={a.analysis_id}>
                    <div className="label">{a.card.variable} · {a.card.region ?? `${a.card.region_a} vs ${a.card.region_b}`}{a.card.data_kind !== "real" ? ` · ${a.card.data_kind} data` : ""}</div>
                    {a.card.per_decade && <div className="value">{fmtSigned(a.card.per_decade.sen)} {a.card.units}/decade</div>}
                    {a.card.difference_per_decade !== undefined && <div className="value">{fmtSigned(a.card.difference_per_decade)} {a.card.units}/decade</div>}
                    <div className="sub">
                      {a.card.significant ? "Significant (both tests agree)" : "Not significant"}
                      {a.card.p_mann_kendall !== undefined && ` · MK p ${fmtP(a.card.p_mann_kendall)}`}
                    </div>
                    <div className="sub"><Link href={`/api/reports/${a.analysis_id}/export?format=pdf`}>PDF</Link> · <Link href={`/embed/${a.analysis_id}`}>card</Link></div>
                  </div>
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
      {status?.enabled && <p className="small muted">AI service: {status.provider} ({status.model}). Limits per visitor and per day keep costs bounded.</p>}
    </div>
  );
}
