"use client";

// Shared by the Admin panel and the Data import page: administrator sign-in (sessions), the NASA
// Earthdata account that imports use, and small helpers.

import { useEffect, useState } from "react";
import Panel from "@/components/Panel";
import { adminSignIn, adminSignOut, ApiError, apiGet, apiSend } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

// ---- types (from /api/admin/*) -----------------------------------------------------------

export type Login = { configured: boolean; method: string; where: string; username: string | null; problem?: string };
export type CheckResult = { product: string; access: string; ok: boolean; detail: string };
export type AccessCheck = { status: "checking" | "done" | "failed"; checked_at?: string; ok?: number; total?: number; results?: CheckResult[]; error?: string; login?: boolean };
export type Worker = { state: "idle" | "starting" | "running"; queued: number; queued_products: string[]; job: null | { id: number; product: string; variables: string[]; started_at: string | null; progress: Progress } };
export type Progress = { stage?: string; done?: number; total?: number; variable?: string; index?: number; variables?: string[]; stored?: Record<string, string> };
export type SessionInfo = { id: string; created_at: string; last_seen: string; expires_at: string; remember: boolean; browser: string; current: boolean };
export type Overview = { role: "local" | "admin" | null; session: SessionInfo | null; can_act: boolean; token_source: "setting" | "file"; login: Login; access_check: AccessCheck | null; worker: Worker };

export type Act = <T>(fn: () => Promise<T>, ok?: (r: T) => string | null) => Promise<T | null>;

// ---- formatting and icons ----------------------------------------------------------------------

export function fmtWhen(iso: string | null | undefined, lang: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(lang === "es" ? "es-ES" : "en-US", { dateStyle: "short", timeStyle: "short" });
}


export const Icon = ({ d, size = 16 }: { d: string; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);
export const KEY = "M15 7a4 4 0 1 1-3.4 6.1L4 20.7V17h3v-3h3l1.6-1.6A4 4 0 0 1 15 7ZM16 10h.01";
export const LOCK = "M6 11h12v10H6zM8.5 11V7.5a3.5 3.5 0 0 1 7 0V11";
export const GEAR = "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z";
export const CLOUD = "M7 18a4.5 4.5 0 0 1-.6-9A6 6 0 0 1 18 9.5a4 4 0 0 1-1 8.5ZM12 11v6M9.5 14.5 12 17l2.5-2.5";
export const DB = "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3ZM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3";
export const PULSE = "M3 12h4l3-8 4 16 3-8h4";

// product id -> title, shared by the cards (fetched once)
let titleCache: Record<string, string> | null = null;
export function useCatalogTitles(): Record<string, string> {
  const [titles, setTitles] = useState<Record<string, string>>(titleCache ?? {});
  useEffect(() => {
    if (titleCache) return;
    apiGet<{ rows: { id: string; short_name: string; archive: string }[] }>("/admin/catalog").then((c) => {
      titleCache = Object.fromEntries(c.rows.map((r) => [r.id, `${r.short_name} (${r.archive})`]));
      setTitles(titleCache);
    }).catch(() => {});
  }, []);
  return titles;
}

// ---- administrator sign-in ---------------------------------------------------------------------

export function AdminSignIn({ ov, onChange }: { ov: Overview; onChange: () => void }) {
  const { t, lang } = useI18n();
  const [token, setToken] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (ov.role === "admin") {
    return (
      <p className="small muted signed-in">
        {ov.session
          ? t("Signed in as administrator until {when} (renewed while you use it).", { when: fmtWhen(ov.session.expires_at, lang) })
          : t("Signed in as administrator.")}{" "}
        <button type="button" className="btn-sm" onClick={async () => { await adminSignOut().catch(() => {}); onChange(); }}>{t("Sign out")}</button>
      </p>
    );
  }
  return (
    <section className="dash-section" aria-labelledby="admin-h">
      <Panel as="div">
        <h2 id="admin-h"><Icon d={LOCK} /> {t("Administrator sign-in")}</h2>
        <p className="sub">
          {t("Everyone can see this page. Imports, deletions and account changes need the administrator token. To see it, run this on the server:")}{" "}
          <code>megavir-ingest admin-token</code>
          {ov.token_source === "file" ? <> {t("(or choose your own: MEGAVIR_ADMIN_TOKEN in the server's .env).")}</> : null}
        </p>
        <form className="inline-form" onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setMsg(null);
          try {
            await adminSignIn(token.trim(), remember);
            setToken("");
            onChange();
          } catch (err) {
            setMsg(err instanceof ApiError && err.status === 403 ? t("That token is not right.") : (err as Error).message);
          } finally {
            setBusy(false);
          }
        }}>
          <div className="field">
            <label htmlFor="admin-token">{t("Administrator token")}</label>
            <input id="admin-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <label className="row small remember">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            {t("Keep me signed in on this browser (30 days)")}
          </label>
          <button type="submit" className="primary" disabled={busy || !token.trim()}>{t("Sign in")}</button>
          {msg && <span className="error" role="alert">{msg}</span>}
        </form>
      </Panel>
    </section>
  );
}

// ---- NASA Earthdata account (used by imports) ------------------------------------------------------------------------

export function EarthdataCard({ ov, canAct, act }: { ov: Overview; canAct: boolean; act: Act }) {
  const { t, lang } = useI18n();
  const [editing, setEditing] = useState(false);
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [saving, setSaving] = useState(false);
  const login = ov.login;
  const check = ov.access_check;
  const titles = useCatalogTitles();

  return (
    <section className="dash-section" id="earthdata" aria-labelledby="ed-h">
      <Panel as="div">
        <h2 id="ed-h"><Icon d={KEY} /> {t("NASA Earthdata account")}</h2>
        <p className="sub">{t("Needed to import the sources marked \"Earthdata Login\" on the Data import page. The password is kept only on the server, never in the database, and is never shown again.")}</p>
        <p className="small" style={{ margin: "0 0 6px" }}>
          {!login.configured
            ? t("No Earthdata Login is set on this server yet.")
            : login.method === "token"
              ? t("The server uses an Earthdata token from its environment (EARTHDATA_TOKEN).")
              : login.username
                ? <>{t("Signed in as")} <strong>{login.username}</strong> · {login.method === "netrc" ? t("saved on the server in {where} (readable only by the server)", { where: login.where }) : t("set in the server's environment")}</>
                : t("An Earthdata Login is set on the server.")}
          {login.problem && <span className="error"> {login.problem}</span>}
        </p>
        {check?.status === "checking" && <p className="small muted" role="status">{t("Checking every source… this takes about a minute.")}</p>}
        {check && check.status === "failed" && <p className="small error">{t("The last check did not finish:")} {check.error}</p>}
        {check && check.status === "done" && (
          <>
            <p className="small muted" style={{ margin: "8px 0 0" }}>
              {t("Last check {when}: {ok} of {total} sources can be downloaded.", { when: fmtWhen(check.checked_at, lang), ok: check.ok ?? 0, total: check.total ?? 0 })}
            </p>
            <ul className="check-list">
              {(check.results ?? []).map((r) => (
                <li key={r.product}>
                  <span className={`mark ${r.ok ? "ok" : "fail"}`} aria-hidden="true">{r.ok ? "✓" : "✗"}</span>
                  <span><strong>{titles[r.product] ?? r.product}</strong>: {r.ok ? t("works") : t("does not work")} <span className="muted">— {r.detail}</span></span>
                </li>
              ))}
            </ul>
          </>
        )}
        {!check && login.configured && <p className="small muted">{t("Not checked yet: use “Check again” to test every source with this login.")}</p>}

        {canAct && !editing && (
          <div className="dash-actions">
            <button type="button" className="btn-sm" disabled={check?.status === "checking"} onClick={() => act(() => apiSend("POST", "/admin/earthdata/check"))}>{t("Check again")}</button>
            <button type="button" className="btn-sm" onClick={() => setEditing(true)}>{login.configured ? t("Change account") : t("Add account")}</button>
            {login.configured && login.method === "netrc" && (
              <button type="button" className="btn-sm" onClick={() => {
                if (window.confirm(t("Remove the Earthdata Login from this server? Imports of Earthdata sources stop working until a login is added again."))) {
                  act(() => apiSend("DELETE", "/admin/earthdata"), () => t("The Earthdata Login was removed from the server."));
                }
              }}>{t("Remove")}</button>
            )}
          </div>
        )}
        {canAct && editing && (
          <form className="inline-form" onSubmit={async (e) => {
            e.preventDefault();
            setSaving(true);
            const r = await act(() => apiSend<Login>("PUT", "/admin/earthdata", { username: user, password: pass }), () => t("Saved. Earthdata Login accepted this account."));
            setSaving(false);
            if (r) { setEditing(false); setUser(""); setPass(""); }
          }}>
            <div className="field">
              <label htmlFor="ed-user">{t("Earthdata username")}</label>
              <input id="ed-user" type="text" autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="ed-pass">{t("Password")}</label>
              <input id="ed-pass" type="password" autoComplete="current-password" value={pass} onChange={(e) => setPass(e.target.value)} />
            </div>
            <button type="submit" className="primary" disabled={saving || !user.trim() || !pass}>{saving ? t("Checking with NASA…") : t("Check and save")}</button>
            <button type="button" onClick={() => { setEditing(false); setPass(""); }}>{t("Cancel")}</button>
          </form>
        )}
      </Panel>
    </section>
  );
}
