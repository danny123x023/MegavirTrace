"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { fmtP, fmtSigned } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import Panel from "@/components/Panel";

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
  timing?: { total_s: number; ai_calls: number };
};
type Turn = { q: string; r: Reply };
type Progress = { step: "thinking" | "tool" | "check"; round?: number; tool?: string; variable?: string | null; places?: string[]; query?: string | null };

/** Ask with progress: the server sends one JSON line per step, then the checked answer. */
async function askWithProgress(body: unknown, onProgress: (p: Progress) => void): Promise<Reply> {
  const res = await fetch("/api/ai/ask/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const j = await res.json(); if (typeof j.detail === "string") msg = j.detail; } catch { /* not JSON */ }
    throw new ApiError(msg, res.status);
  }
  if (!res.body) return apiPost<Reply>("/ai/ask", body); // no streaming in this browser
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let result: Reply | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.type === "progress") onProgress(ev as Progress);
      else if (ev.type === "result") result = ev.result as Reply;
    }
  }
  if (!result) throw new Error("The answer did not arrive. Please try again.");
  return result;
}

const EXAMPLES = [
  "Is the whole Earth really warming, and since when?",
  "Is Siberia warming faster than the North Atlantic?",
  "What is changing in the Gulf Coast test box?",
];

export default function AskPage() {
  const { lang, t } = useI18n();
  const tr = t; // "t" is also the name of each turn below
  const [status, setStatus] = useState<{ enabled: boolean; provider: string; model: string | null } | null>(null);
  const [q, setQ] = useState("");
  const [tutor, setTutor] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [busy]);

  function stepText(p: Progress): string {
    if (p.step === "check") return t("Checking every number against the computed results…");
    if (p.step === "thinking") return p.round === 1 ? t("The AI is reading your question…") : t("The AI is reading the results and writing the answer…");
    const places = p.places ?? [];
    if (p.tool === "run_trend_analysis") return t("Running the {variable} analysis for {place}…", { variable: (p.variable ?? "").toLowerCase(), place: places[0] ?? "" });
    if (p.tool === "compare_regions") return t("Comparing {variable} in {a} and {b}…", { variable: (p.variable ?? "").toLowerCase(), a: places[0] ?? "", b: places[1] ?? "" });
    if (p.tool === "scan_region") return t("Testing every variable for {place}…", { place: places[0] ?? "" });
    if (p.tool === "find_places") return t("Looking up “{query}”…", { query: p.query ?? "" });
    return t("Looking up the variables…");
  }
  const [needQuestion, setNeedQuestion] = useState(false);

  useEffect(() => { apiGet<typeof status>("/ai/status").then(setStatus).catch(() => setStatus({ enabled: false, provider: "none", model: null })); }, []);

  async function ask(question: string) {
    if (question.trim().length < 3) {
      setNeedQuestion(true);
      document.getElementById("q")?.focus();
      return;
    }
    setNeedQuestion(false);
    setSteps([]);
    setStartedAt(Date.now());
    setNow(Date.now());
    setBusy(true);
    const history = turns.flatMap((t) => [
      { role: "user", content: t.q },
      ...(t.r.answer ? [{ role: "assistant", content: `${t.r.answer.headline}\n${t.r.answer.explanation}` }] : []),
    ]).slice(-6);
    let r: Reply;
    try {
      r = await askWithProgress({ question, mode: tutor ? "tutor" : "explain", history, lang }, (p) => setSteps((s) => [...s, stepText(p)]));
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
          <Link href="/explore">explore</Link> or <Link href="/compare">compare</Link> any place.
        </p>
      )}

      <section className="card" aria-label="Your question">
        <label htmlFor="q" className="label" style={{ fontWeight: 600 }}>Your question</label>
        <textarea
          id="q" value={q} maxLength={600} placeholder="For example: Is rainfall in the Sahel changing?"
          aria-describedby={needQuestion ? "q-need" : undefined} aria-invalid={needQuestion || undefined}
          onChange={(e) => { setQ(e.target.value); if (e.target.value.trim().length >= 3) setNeedQuestion(false); }}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask(q); }}
        />
        {needQuestion && <p id="q-need" className="small field-hint" role="alert">{t("Type a question first (at least 3 characters).")}</p>}
        <div className="row" style={{ marginTop: 8, justifyContent: "space-between" }}>
          <label className="row small">
            <input type="checkbox" checked={tutor} onChange={(e) => setTutor(e.target.checked)} />
            Tutor mode: guide me with questions instead of explaining
          </label>
          <button type="button" className="primary" disabled={busy || status?.enabled === false} onClick={() => ask(q)}>
            {busy ? t("Running the analyses…") : t("Ask")}
          </button>
        </div>
        <div className="chip-list" style={{ marginTop: 10 }}>
          {EXAMPLES.map((e) => <button key={e} type="button" className="chip" disabled={status?.enabled === false || busy} onClick={() => ask(e)}>{e}</button>)}
        </div>
      </section>

      {busy && (
        <div className="card ai-progress" role="status" aria-live="polite">
          <p className="ai-progress-head">
            <span className="spinner-dot" aria-hidden="true" /> {t("Working on it…")}
            {startedAt && <span className="muted"> {t("{s} s", { s: Math.max(0, Math.round((now - startedAt) / 1000)) })}</span>}
          </p>
          <ol className="ai-steps">
            {steps.map((s, i) => <li key={i} className={i === steps.length - 1 ? "current" : "done"}>{s}</li>)}
          </ol>
        </div>
      )}

      <div className="stack" style={{ marginTop: 16 }} aria-live="polite">
        {turns.map((t, i) => (
          <Panel key={i} aria-label={`Answer ${i + 1}`}>
            <p className="muted small" style={{ marginTop: 0 }}>You asked: {t.q}</p>
            {t.r.mode === "answered" && t.r.answer && (
              <>
                <h2>{t.r.answer.headline}</h2>
                {t.r.answer.explanation.split(/\n+/).map((p, j) => <p key={j}>{p}</p>)}
                <p className="small muted">
                  ✓ Number check passed: {t.r.check?.numbers_checked ?? 0} numbers match the stored analyses.
                  {t.r.timing && <> · {tr("Answered in {s} s", { s: t.r.timing.total_s })}</>}
                </p>
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
          </Panel>
        ))}
      </div>
      {status?.enabled && <p className="small muted">AI service: {status.provider} ({status.model}). Limits per visitor and per day keep costs bounded.</p>}
    </div>
  );
}
