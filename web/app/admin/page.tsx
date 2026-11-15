"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Panel from "@/components/Panel";
import { AdminSignIn, EarthdataCard, fmtWhen, GEAR, Icon, KEY, LOCK, type Overview, type SessionInfo } from "@/components/AdminShared";
import { adminSession, apiGet, apiSend, forgetAdminSession } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// Admin panel: which AI service answers (Claude or Z.ai) with which key and model, the NASA
// Earthdata account that data imports use, and the administrator sessions.  Keys stay on the
// server: this page only ever sees the last four characters.

type Provider = "anthropic" | "zai";
type ProviderView = {
  label: string; key_set: boolean; key_hint: string | null; key_source: "panel" | "env" | null;
  model: string; suggested_models: string[]; ready: boolean;
};
type AiView = {
  active: string; chosen: string; chosen_in: "panel" | "env"; fallback: boolean; fallback_to: string | null;
  providers: Record<Provider, ProviderView>; updated_at: string | null;
  usage: { hourly_limit_per_visitor: number; daily_cap: number; used_today: number };
};
type Act = <T>(fn: () => Promise<T>, ok?: (r: T) => string | null) => Promise<T | null>;

const AI = "M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M6 18l2-2M16 8l2-2M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z";
const PROVIDERS: Provider[] = ["anthropic", "zai"];
const OTHER_MODEL = "__other__"; // the dropdown entry that opens a box for any model name

export default function AdminPage() {
  const { t } = useI18n();
  const [ov, setOv] = useState<Overview | null>(null);
  const [ai, setAi] = useState<AiView | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const o = await apiGet<Overview>("/admin/overview");
      if (o.role === null && adminSession()) forgetAdminSession(); // ended elsewhere or expired
      setOv(o);
      if (o.can_act) {
        const [a, s] = await Promise.all([apiGet<AiView>("/admin/ai"), apiGet<{ sessions: SessionInfo[] }>("/admin/sessions")]);
        setAi(a);
        setSessions(s.sessions);
      } else {
        setAi(null);
        setSessions(null);
      }
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  // while the Earthdata check runs, follow it
  useEffect(() => {
    if (ov?.access_check?.status !== "checking") return;
    const id = window.setInterval(load, 3000);
    return () => window.clearInterval(id);
  }, [ov?.access_check?.status, load]);

  const act: Act = useCallback(async (fn, ok) => {
    setError(null);
    setNotice(null);
    try {
      const r = await fn();
      const msg = ok?.(r);
      if (msg) setNotice(msg);
      await load();
      return r;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [load]);

  const activeLabel = !ai ? "…" : ai.active === "none" ? t("off") : `${ai.providers[ai.active as Provider]?.label ?? ai.active} · ${ai.providers[ai.active as Provider]?.model ?? ""}`;

  return (
    <div>
      <h1>{t("Admin panel")}</h1>
      <p className="lede">{t("Choose which AI service answers questions and with which key, manage the NASA Earthdata account that data imports use, and see who is signed in as administrator.")}</p>

      <div className="status-row">
        <span className="stat-chip"><Icon d={LOCK} size={14} /> {ov?.role === "admin" ? t("Signed in as administrator") : t("Not signed in")}</span>
        {ai && <span className="stat-chip"><Icon d={AI} size={14} /> {t("AI service:")} <strong>{activeLabel}</strong></span>}
        {ov && <span className="stat-chip"><Icon d={KEY} size={14} /> {t("NASA Earthdata Login:")} <strong>{ov.login.configured ? t("configured") : t("not configured")}</strong></span>}
      </div>

      {notice && <p className="notice" role="status">{notice} <button type="button" className="btn-sm" onClick={() => setNotice(null)}>{t("Dismiss")}</button></p>}
      {error && <p className="error" role="alert">{error}</p>}

      {ov && <AdminSignIn ov={ov} onChange={load} />}
      {ov?.can_act && ai && <AiSection ai={ai} act={act} />}
      {ov?.can_act && <EarthdataCard ov={ov} canAct act={act} />}
      {ov?.can_act && sessions && <SessionsSection sessions={sessions} act={act} onSignedOut={load} />}

      <p className="small"><Link href="/imports">{t("Go to the data import dashboard")}</Link></p>
    </div>
  );
}

// ---- AI service ----------------------------------------------------------------------------------

function AiSection({ ai, act }: { ai: AiView; act: Act }) {
  const { t, lang } = useI18n();
  const both = ai.providers.anthropic.ready && ai.providers.zai.ready;
  const choose = (active: string) => act(() => apiSend("PUT", "/admin/ai", { active }), () => t("Saved. The AI service changes at once for every visitor."));
  return (
    <section className="dash-section" aria-labelledby="ai-h">
      <Panel as="div">
        <h2 id="ai-h"><Icon d={AI} /> {t("AI service")}</h2>
        <p className="sub">{t("Keys are kept only on the server (readable by the server alone) and are never shown again: the panel sees their last four characters. A new key is checked with the service before it is saved.")}</p>

        <fieldset className="ai-choice">
          <legend>{t("Which service answers questions")}</legend>
          <div className="choice-grid ai-choice-grid">
            {[...PROVIDERS, "none"].map((p) => {
              const v = p === "none" ? null : ai.providers[p as Provider];
              const on = ai.active === p || (p === "none" && ai.active === "none");
              return (
                <button
                  key={p} type="button" className="choice-card" aria-pressed={on}
                  disabled={!!v && !v.ready}
                  onClick={() => !on && choose(p)}
                >
                  <span className="choice-title">{v ? v.label : t("Off")}</span>
                  <span className="choice-meta">
                    {v ? (v.ready ? t("Model: {m}", { m: v.model }) : t("Add a key first")) : t("Answers show the computed verdicts only")}
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>
        {ai.chosen_in === "env" && <p className="small muted">{t("Chosen in the server's .env for now; choosing here overrides it.")}</p>}
        <label className="row small" style={{ marginTop: 10 }}>
          <input
            type="checkbox" checked={ai.fallback} disabled={!both && !ai.fallback}
            onChange={(e) => act(() => apiSend("PUT", "/admin/ai", { fallback: e.target.checked }))}
          />
          {t("If the chosen service fails, let the other one answer")}
          {!both && <span className="muted"> ({t("needs keys for both")})</span>}
        </label>
        <p className="small muted" style={{ margin: "8px 0 0" }}>
          {t("Today: {used} of {cap} AI answers used (at most {hour} per visitor per hour).", { used: ai.usage.used_today, cap: ai.usage.daily_cap, hour: ai.usage.hourly_limit_per_visitor })}
          {ai.updated_at && <> · {t("Last changed {when}", { when: fmtWhen(ai.updated_at, lang) })}</>}
        </p>

        <div className="ai-providers">
          {PROVIDERS.map((p) => <ProviderCard key={p} p={p} v={ai.providers[p]} active={ai.active === p} act={act} />)}
        </div>
      </Panel>
    </section>
  );
}

function ProviderCard({ p, v, active, act }: { p: Provider; v: ProviderView; active: boolean; act: Act }) {
  const { t } = useI18n();
  const [key, setKey] = useState("");
  const [model, setModel] = useState(v.model);
  const [typing, setTyping] = useState(false); // "Other model…" was chosen: a name is typed
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; detail: string } | null>(null);
  useEffect(() => { setModel(v.model); setTyping(false); }, [v.model]);
  const known = v.suggested_models;
  const custom = typing || (!!model && !known.includes(model)); // a model that is not in the list
  return (
    <div className="ai-provider card">
      <h3>
        {v.label}
        {active && <span className="badge badge-real">{t("answering now")}</span>}
      </h3>
      <p className="small" style={{ margin: "0 0 8px" }}>
        {v.key_set
          ? <>{t("Key")} <code>{v.key_hint}</code> · {v.key_source === "env" ? t("from the server's .env") : t("saved in this panel")}</>
          : t("No key yet.")}
      </p>

      <form className="inline-form" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setTest(null);
        const r = await act(
          () => apiSend<{ check: { detail: string } }>("PUT", `/admin/ai/keys/${p}`, { api_key: key.trim(), model: model.trim() || undefined }),
          (res) => res.check.detail,
        );
        setBusy(false);
        if (r) setKey("");
      }}>
        <div className="field">
          <label htmlFor={`key-${p}`}>{v.key_set ? t("Replace the key") : t("API key")}</label>
          <input
            id={`key-${p}`} type="password" autoComplete="off" spellCheck={false} value={key}
            placeholder={p === "anthropic" ? "sk-ant-api03-…" : ""} onChange={(e) => setKey(e.target.value)}
          />
        </div>
        <button type="submit" className="primary" disabled={busy || key.trim().length < 10}>{busy ? t("Checking with the service…") : t("Check and save")}</button>
      </form>

      <form className="inline-form" onSubmit={(e) => {
        e.preventDefault();
        act(() => apiSend("PUT", "/admin/ai", { models: { [p]: model.trim() } }), () => t("Model saved."));
      }}>
        <div className="field">
          <label htmlFor={`model-${p}`}>{t("Model")}</label>
          <select
            id={`model-${p}`} value={custom ? OTHER_MODEL : model}
            onChange={(e) => {
              const m = e.target.value;
              if (m === OTHER_MODEL) { setTyping(true); setModel(known.includes(model) ? "" : model); }
              else { setTyping(false); setModel(m); }
            }}
          >
            {!model && !custom && <option value="" disabled>{t("Choose a model…")}</option>}
            {known.map((m) => <option key={m} value={m}>{m}{m === v.model ? ` (${t("saved")})` : ""}</option>)}
            <option value={OTHER_MODEL}>{t("Other model…")}</option>
          </select>
        </div>
        {custom && (
          <div className="field">
            <label htmlFor={`model-name-${p}`}>{t("Model name")}</label>
            <input
              id={`model-name-${p}`} type="text" spellCheck={false} autoComplete="off" value={model}
              placeholder={p === "anthropic" ? "claude-…" : "glm-…"} onChange={(e) => setModel(e.target.value)}
            />
          </div>
        )}
        <button type="submit" className={model.trim() && model.trim() !== v.model ? "primary" : undefined} disabled={!model.trim() || model.trim() === v.model}>{t("Save model")}</button>
      </form>

      {v.key_set && (
        <div className="dash-actions">
          <button type="button" className="btn-sm" onClick={async () => {
            setTest(null);
            const r = await act(() => apiSend<{ ok: boolean; detail: string }>("POST", `/admin/ai/test/${p}`));
            if (r) setTest(r);
          }}>{t("Test the key")}</button>
          {v.key_source === "panel" && (
            <button type="button" className="btn-sm" onClick={() => {
              if (window.confirm(t("Remove this key from the server? If this service is answering now, the AI is switched off until a key is added again."))) {
                act(() => apiSend("DELETE", `/admin/ai/keys/${p}`), () => t("The key was removed from the server."));
              }
            }}>{t("Remove key")}</button>
          )}
          {test && <span className={`small ${test.ok ? "ok-text" : "error-text"}`} role="status">{test.ok ? "✓ " : "✗ "}{test.detail}</span>}
        </div>
      )}
    </div>
  );
}

// ---- administrator sessions ------------------------------------------------------------------------

function SessionsSection({ sessions, act, onSignedOut }: { sessions: SessionInfo[]; act: Act; onSignedOut: () => void }) {
  const { t, lang } = useI18n();
  const others = sessions.filter((s) => !s.current).length;
  return (
    <section className="dash-section" aria-labelledby="sess-h">
      <Panel as="div">
        <h2 id="sess-h"><Icon d={GEAR} /> {t("Administrator sessions")}</h2>
        <p className="sub">{t("Every browser signed in with the administrator token. A session ends after 12 hours without use, or 30 days with “keep me signed in”. Changing MEGAVIR_ADMIN_TOKEN does not end sessions: end them here.")}</p>
        <div className="dash-scroll">
          <table className="dash">
            <thead>
              <tr>
                <th scope="col">{t("Browser")}</th>
                <th scope="col">{t("Signed in")}</th>
                <th scope="col">{t("Last used")}</th>
                <th scope="col">{t("Ends")}</th>
                <th scope="col"><span className="visually-hidden">{t("Actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td>{s.browser} {s.current && <span className="badge badge-real">{t("this browser")}</span>}</td>
                  <td>{fmtWhen(s.created_at, lang)}</td>
                  <td>{fmtWhen(s.last_seen, lang)}</td>
                  <td>{fmtWhen(s.expires_at, lang)}{s.remember ? ` · ${t("kept signed in")}` : ""}</td>
                  <td>
                    <button type="button" className="btn-sm" onClick={() =>
                      s.current
                        ? act(() => apiSend("DELETE", "/admin/sessions/current")).then(() => { forgetAdminSession(); onSignedOut(); })
                        : act(() => apiSend("DELETE", `/admin/sessions/${s.id}`), () => t("That session was ended."))
                    }>{s.current ? t("Sign out") : t("End session")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {others > 0 && (
          <div className="dash-actions">
            <button type="button" className="btn-sm" onClick={() => act(() => apiSend<{ ended: number }>("DELETE", "/admin/sessions"), (r) => t("{n} other sessions ended.", { n: r.ended }))}>
              {t("Sign out everywhere else")}
            </button>
          </div>
        )}
      </Panel>
    </section>
  );
}
