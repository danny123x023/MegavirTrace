"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import Panel from "@/components/Panel";
import {
  type Act, AdminSignIn, CLOUD, DB, fmtWhen, GEAR, Icon, KEY, LOCK, type Overview, PULSE, type Worker,
} from "@/components/AdminShared";
import { useI18n } from "@/lib/i18n";

// ---- types (from /api/admin/*) -----------------------------------------------------------

type Nasa = { first_month?: string; last_month?: string; files?: number; bytes?: number | null; approx_size?: boolean; error?: string };
type CatalogRow = {
  id: string; title: string; short_name: string; archive: string; login_required: boolean; access_note: string; variables: string[];
  nasa: Nasa; db: null | { first_month: string; last_month: string; imported_at: string; variables: string[] };
  status: "up_to_date" | "newer" | "in_database" | "stand_in" | "not_imported"; newer_months: number;
};
type Catalog = { checked_at: string | null; rows: CatalogRow[]; counts: Record<string, number> };
type JobResult = { action: string; version?: number; months?: number; detail?: string };
type HistoryItem = {
  kind: "job" | "command_line"; id: number | string; product: string | null; product_title: string | null; variables: string[];
  status: "queued" | "running" | "done" | "failed"; started_at: string | null; took_s: number | null; summary: string;
  results: Record<string, JobResult>; requested_by: string;
};
type History = { items: HistoryItem[]; total: number; page: number; per_page: number };
type DbRow = {
  variable: string; name: string; product: string | null; product_title: string | null; archive: string | null; kind: string | null; version?: number;
  first_month?: string; last_month?: string; months?: number; res_deg?: number; size_bytes?: number | null; download_bytes?: number | null;
  imported_at?: string; stored_days?: number; compare?: string; newer_months?: number; nasa_last_month?: string | null;
};
type Db = { rows: DbRow[]; counts: Record<string, number> };

// ---- formatting ------------------------------------------------------------------------------

function fmtBytes(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

function fmtDuration(s?: number | null): string {
  if (s === null || s === undefined) return "—";
  if (s < 60) return `${Math.max(1, Math.round(s))} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}


// ---- page ---------------------------------------------------------------------------------------

export default function ImportsPage() {
  const { t, lang } = useI18n();
  const [ov, setOv] = useState<Overview | null>(null);
  const [cat, setCat] = useState<Catalog | null>(null);
  const [hist, setHist] = useState<History | null>(null);
  const [db, setDb] = useState<Db | null>(null);
  const [histQuery, setHistQuery] = useState({ status: "", variable: "", page: 1 });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadOverview = useCallback(() => apiGet<Overview>("/admin/overview").then(setOv), []);
  const loadCatalog = useCallback(() => apiGet<Catalog>("/admin/catalog").then(setCat), []);
  const loadDb = useCallback(() => apiGet<Db>("/admin/database").then(setDb), []);
  const loadHistory = useCallback(
    () => apiGet<History>("/admin/imports", { status: histQuery.status || undefined, variable: histQuery.variable || undefined, page: histQuery.page }).then(setHist),
    [histQuery],
  );
  const loadAll = useCallback(async () => {
    try {
      await Promise.all([loadOverview(), loadCatalog(), loadDb(), loadHistory()]);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [loadOverview, loadCatalog, loadDb, loadHistory]);

  useEffect(() => { loadAll(); }, [loadAll]);

  // poll: every few seconds while something runs, otherwise slowly
  const busy = ov?.worker.state !== "idle" || ov?.access_check?.status === "checking";
  useEffect(() => {
    const id = window.setInterval(() => { loadAll(); }, busy ? 3000 : 15000);
    return () => window.clearInterval(id);
  }, [busy, loadAll]);

  // when a job finishes, the stored data and NASA comparison change too
  const runningId = ov?.worker.job?.id ?? null;
  const [lastRunning, setLastRunning] = useState<number | null>(null);
  useEffect(() => {
    if (lastRunning !== null && runningId !== lastRunning) { loadCatalog(); loadDb(); }
    setLastRunning(runningId);
  }, [runningId, lastRunning, loadCatalog, loadDb]);

  const act = useCallback(async <T,>(fn: () => Promise<T>, ok?: (r: T) => string | null) => {
    setError(null);
    try {
      const r = await fn();
      const msg = ok?.(r);
      if (msg) setNotice(msg);
      await loadAll();
      return r;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [loadAll]);

  const canAct = !!ov?.can_act;
  const login = ov?.login;
  const workerLabel = !ov ? "…" : ov.worker.state === "running" ? t("running") : ov.worker.state === "starting" ? t("starting") : t("idle");

  return (
    <div>
      <h1>{t("Data import dashboard")}</h1>
      <p className="lede">{t("See what NASA has, choose what to import into MegavirTrace's database, follow each import as it runs, and check what is stored and for how long.")}</p>

      <div className="status-row">
        <span className="stat-chip"><Icon d={KEY} size={14} /> {t("NASA Earthdata Login:")} <strong>{!login ? "…" : login.configured ? t("configured") : t("not configured")}</strong></span>
        <span className="stat-chip"><Icon d={LOCK} size={14} /> {ov?.role === "admin" ? t("Signed in as administrator") : ov?.role === "local" ? t("On the server itself: imports allowed") : t("Viewing only: imports need the administrator token")}</span>
        <span className="stat-chip"><Icon d={GEAR} size={14} /> {t("Worker:")} <strong>{workerLabel}</strong>{ov && ov.worker.queued > 0 && <> · {t("{n} queued", { n: ov.worker.queued })}</>}</span>
      </div>

      {notice && <p className="notice" role="status">{notice} <button type="button" className="btn-sm" onClick={() => setNotice(null)}>{t("Dismiss")}</button></p>}
      {error && <p className="error" role="alert">{error}</p>}

      {ov && (!ov.can_act || ov.role === "admin") && <AdminSignIn ov={ov} onChange={loadAll} />}
      {ov && <EarthdataSummary ov={ov} />}
      <CatalogSection cat={cat} ov={ov} canAct={canAct} act={act} />
      <ProgressSection ov={ov} hist={hist} query={histQuery} setQuery={setHistQuery} canAct={canAct} act={act} />
      <DatabaseSection db={db} />
    </div>
  );
}


// ---- NASA Earthdata account: managed in the Admin panel ---------------------------------------

function EarthdataSummary({ ov }: { ov: Overview }) {
  const { t, lang } = useI18n();
  const login = ov.login;
  const check = ov.access_check;
  return (
    <section className="dash-section" aria-labelledby="ed-h">
      <Panel as="div">
        <h2 id="ed-h"><Icon d={KEY} /> {t("NASA Earthdata account")}</h2>
        <p className="small" style={{ margin: "0 0 6px" }}>
          {!login.configured
            ? t("No Earthdata Login is set on this server yet.")
            : login.username ? <>{t("Signed in as")} <strong>{login.username}</strong></> : t("An Earthdata Login is set on the server.")}
          {check?.status === "done" && <> · {t("Last check {when}: {ok} of {total} sources can be downloaded.", { when: fmtWhen(check.checked_at, lang), ok: check.ok ?? 0, total: check.total ?? 0 })}</>}
          {check?.status === "checking" && <> · {t("Checking every source… this takes about a minute.")}</>}
        </p>
        <p className="small" style={{ margin: 0 }}>
          <Link href="/admin#earthdata">{t("Manage the account and check every source in the Admin panel")}</Link>
        </p>
      </Panel>
    </section>
  );
}

// ---- 1. Available from NASA ------------------------------------------------------------------

const CAT_TABS = [
  { id: "all", label: "All" },
  { id: "in_database", label: "In database" },
  { id: "newer", label: "Newer months at NASA" },
  { id: "not_imported", label: "Not imported" },
] as const;

function CatalogSection({ cat, ov, canAct, act }: { cat: Catalog | null; ov: Overview | null; canAct: boolean; act: Act }) {
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<(typeof CAT_TABS)[number]["id"]>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [again, setAgain] = useState(false);
  const [checking, setChecking] = useState(false);

  const busyProducts = new Set([...(ov?.worker.queued_products ?? []), ...(ov?.worker.job ? [ov.worker.job.product] : [])]);
  const rows = (cat?.rows ?? []).filter((r) => tab === "all" || (tab === "in_database" ? r.db : tab === "newer" ? r.status === "newer" : !r.db));
  const selectable = (r: CatalogRow) => canAct && !busyProducts.has(r.id) && (again || r.status !== "up_to_date");
  const chosen = [...selected].filter((id) => cat?.rows.some((r) => r.id === id && selectable(r)));
  const c = cat?.counts;

  return (
    <section className="dash-section" aria-labelledby="cat-h">
      <Panel as="div">
        <h2 id="cat-h"><Icon d={CLOUD} /> {t("1. Available from NASA")}</h2>
        <p className="sub">
          {cat?.checked_at
            ? t("Live from NASA's public catalogues (checked {when}). Choose sources to import.", { when: fmtWhen(cat.checked_at, lang) })
            : t("NASA's catalogues have not been checked yet: use “Check NASA again”.")}
        </p>
        {c && (
          <p className="dash-summary">
            <strong>{t("{a} of {b} NASA sources have real data in your database", { a: c.in_database, b: c.all })}</strong>{" "}
            ({t("{u} up to date, {n} with newer months at NASA", { u: c.up_to_date, n: c.newer })}). {t("{k} are not imported yet.", { k: c.not_imported })}
          </p>
        )}
        <div className="table-tools">
          <div className="chip-list" role="group" aria-label={t("Show sources")}>
            {CAT_TABS.map((x) => (
              <button key={x.id} type="button" className="chip btn-sm" aria-pressed={tab === x.id} onClick={() => setTab(x.id)}>
                {t(x.label)} ({x.id === "all" ? (c?.all ?? 0) : x.id === "in_database" ? (c?.in_database ?? 0) : x.id === "newer" ? (c?.newer ?? 0) : (c?.not_imported ?? 0)})
              </button>
            ))}
          </div>
        </div>
        <div className="dash-scroll">
          <table className="dash">
            <thead>
              <tr>
                <th scope="col"><span className="visually-hidden">{t("Select")}</span></th>
                <th scope="col">{t("Data")}</th>
                <th scope="col">{t("At NASA")}</th>
                <th scope="col">{t("Download")}</th>
                <th scope="col">{t("In your database")}</th>
                <th scope="col">{t("Access")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const ok = selectable(r);
                return (
                  <tr key={r.id}>
                    <td>
                      <input type="checkbox" aria-label={t("Select {name}", { name: r.short_name })} disabled={!ok} checked={ok && selected.has(r.id)}
                        onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(r.id); else n.delete(r.id); return n; })} />
                    </td>
                    <td style={{ maxWidth: 320 }}><strong className="clamp" title={r.title}>{r.title}</strong><span className="line2">{r.archive} · {r.short_name}</span></td>
                    <td className="num">
                      {r.nasa.error ? <span className="pill fail">{t("could not check")}</span>
                        : r.nasa.last_month ? <>{r.nasa.first_month} {t("to")} {r.nasa.last_month}<span className="line2">{t("{n} files", { n: r.nasa.files ?? "?" })}</span></>
                        : <span className="muted">{t("not checked")}</span>}
                      {r.nasa.error && <span className="line2">{r.nasa.error}</span>}
                    </td>
                    <td className="num">
                      {r.nasa.bytes ? <>{r.nasa.approx_size ? "≈ " : ""}{fmtBytes(r.nasa.bytes)}</> : "—"}
                      {r.login_required && r.access_note.startsWith("OPeNDAP") && <span className="line2">{t("as whole files; the subset downloaded is smaller")}</span>}
                    </td>
                    <td>
                      <StatusPill row={r} />
                      {r.db && <span className="line2">{r.db.first_month} {t("to")} {r.db.last_month} · {fmtWhen(r.db.imported_at, lang)}</span>}
                      <span className="line2">{r.status === "up_to_date" ? t("Nothing new to import") : r.status === "newer" ? t("{n} newer months to import", { n: r.newer_months }) : busyProducts.has(r.id) ? t("Import queued or running") : null}</span>
                    </td>
                    <td><strong>{r.login_required ? t("Earthdata Login") : t("Public, no login")}</strong><span className="line2">{t(r.access_note)}</span></td>
                  </tr>
                );
              })}
              {cat && rows.length === 0 && <tr><td colSpan={6} className="muted">{t("No sources in this view.")}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="dash-actions">
          <button type="button" className="primary" disabled={!canAct || chosen.length === 0} onClick={async () => {
            const r = await act(() => apiSend<{ queued: { product: string }[]; skipped: { product: string; reason: string }[] }>("POST", "/admin/imports", { products: chosen }),
              (res) => t("{n} import(s) queued.", { n: res.queued.length }) + (res.skipped.length ? " " + res.skipped.map((s) => `${s.product}: ${s.reason}`).join("; ") : ""));
            if (r) setSelected(new Set());
          }}>{t("Import selected ({n})", { n: chosen.length })}</button>
          <button type="button" disabled={!canAct || checking} onClick={async () => {
            setChecking(true);
            await act(() => apiSend("POST", "/admin/catalog/refresh"));
            setChecking(false);
          }}>{checking ? t("Checking NASA…") : t("Check NASA again")}</button>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={again} disabled={!canAct} onChange={(e) => setAgain(e.target.checked)} />
            {t("Also allow sources that are already in the database and up to date (import them again)")}
          </label>
        </div>
        <p className="hint">{t("Nothing is imported twice: files already on disk are not downloaded again, and an import whose data is identical to what is stored keeps the stored version. Each import covers the source's whole record.")}</p>
      </Panel>
    </section>
  );
}

function StatusPill({ row }: { row: CatalogRow }) {
  const { t } = useI18n();
  if (row.status === "up_to_date") return <span className="pill ok">{t("In database · up to date")}</span>;
  if (row.status === "newer") return <span className="pill warn">{t("In database · {n} newer months at NASA", { n: row.newer_months })}</span>;
  if (row.status === "in_database") return <span className="pill ok">{t("In database")}</span>;
  if (row.status === "stand_in") return <span className="pill info">{t("Test data only")}</span>;
  return <span className="pill">{t("Not imported")}</span>;
}

// ---- 2. Import progress ----------------------------------------------------------------------

const STAGE: Record<string, string> = {
  starting: "Starting…",
  download: "Downloading files",
  build: "Building the grid",
  swap: "Swapping the new version in",
  precompute: "Precomputing statistics for the presets",
  finished: "Finishing",
};

function ProgressSection({ ov, hist, query, setQuery, canAct, act }: {
  ov: Overview | null; hist: History | null; query: { status: string; variable: string; page: number };
  setQuery: (q: { status: string; variable: string; page: number }) => void; canAct: boolean; act: Act;
}) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [now, setNow] = useState(() => Date.now());
  const job = ov?.worker.job;
  useEffect(() => {
    if (!job) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [job]);

  const p = job?.progress ?? {};
  const pct = p.stage === "download" && p.total ? Math.round(((p.done ?? 0) / p.total) * 100) : p.stage === "build" && p.total ? Math.round((((p.index ?? 0) + 0.5) / p.total) * 100) : null;
  const stageText = (() => {
    const base = t(STAGE[p.stage ?? "starting"] ?? p.stage ?? "");
    if (p.stage === "download" && p.total) return `${base}: ${t("{a} of {b}", { a: p.done ?? 0, b: p.total })}`;
    if (p.stage === "build" && p.variable) return `${base}: ${p.variable} (${t("{a} of {b}", { a: (p.index ?? 0) + 1, b: p.total ?? 1 })})`;
    if (p.stage === "precompute" && p.variables) return `${base}: ${p.variables.join(", ")}`;
    return base;
  })();
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const pages = hist ? Math.max(1, Math.ceil(hist.total / hist.per_page)) : 1;

  return (
    <section className="dash-section" aria-labelledby="prog-h">
      <Panel as="div">
        <h2 id="prog-h"><Icon d={PULSE} /> {t("2. Import progress")}</h2>
        <p className="sub">{t("Each import downloads, builds the grid, then swaps it in, and records what it did with every variable. Updates every few seconds.")}</p>
        <div aria-live="polite">
          {job ? (
            <div className="running-card">
              <strong>{t("Importing {name}", { name: job.product })}</strong> <span className="muted small">· {job.variables.join(", ")} · {t("running for {d}", { d: fmtDuration(job.started_at ? (now - Date.parse(job.started_at)) / 1000 : 0) })}</span>
              <div className="progress" role="progressbar" aria-label={t("Import progress")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined}>
                <span style={{ width: `${pct ?? 5}%` }} />
              </div>
              <span className="small">{stageText}</span>
              {p.stored && Object.keys(p.stored).length > 0 && (
                <span className="small muted"> · {Object.entries(p.stored).map(([v, a]) => `${v}: ${t(a)}`).join(", ")}</span>
              )}
            </div>
          ) : (
            <p className="small muted" style={{ margin: "0 0 14px" }}>{ov && ov.worker.queued > 0 ? t("Starting the next import…") : t("No import running.")}</p>
          )}
        </div>

        <h3 style={{ marginTop: 8 }}>{t("History")}</h3>
        <div className="table-tools">
          <div className="row" style={{ gap: 8 }}>
            <select aria-label={t("Filter by status")} value={query.status} onChange={(e) => setQuery({ ...query, status: e.target.value, page: 1 })}>
              <option value="">{t("All statuses")}</option>
              <option value="queued">{t("Queued")}</option>
              <option value="running">{t("Running")}</option>
              <option value="done">{t("Done")}</option>
              <option value="failed">{t("Failed")}</option>
            </select>
            <input type="search" aria-label={t("Filter by variable")} placeholder={t("Filter by variable")} value={query.variable}
              onChange={(e) => setQuery({ ...query, variable: e.target.value, page: 1 })} />
          </div>
          <button type="button" className="btn-sm" disabled={!canAct} onClick={() => {
            if (window.confirm(t("Delete every finished import from the history? The stored data is not affected."))) {
              act(() => apiSend<{ deleted: number }>("DELETE", "/admin/imports"), (r) => t("{n} finished import(s) deleted from the history.", { n: r.deleted }));
            }
          }}>{t("Delete finished jobs")}</button>
        </div>
        <div className="dash-scroll">
          <table className="dash">
            <thead>
              <tr>
                <th scope="col"><span className="visually-hidden">{t("Details")}</span></th>
                <th scope="col">{t("Started")}</th>
                <th scope="col">{t("Variables")}</th>
                <th scope="col">{t("Status")}</th>
                <th scope="col">{t("Took")}</th>
                <th scope="col">{t("What happened")}</th>
                <th scope="col"><span className="visually-hidden">{t("Actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {(hist?.items ?? []).map((h) => {
                const k = String(h.id);
                const isOpen = open.has(k);
                return (
                  <Fragment key={k}>
                    <tr>
                      <td>
                        <button type="button" className="btn-icon" aria-expanded={isOpen} aria-label={t("Details of this import")} onClick={() => toggle(k)}>
                          <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                        </button>
                      </td>
                      <td className="num">{fmtWhen(h.started_at, lang)}</td>
                      <td>{h.variables.join(", ")}<span className="line2">{h.product_title}</span></td>
                      <td><JobPill status={h.status} /></td>
                      <td className="num">{h.status === "running" ? "…" : fmtDuration(h.took_s)}</td>
                      <td>{h.summary ? t(h.summary) : h.status === "queued" ? t("waiting for the worker") : "—"}{h.kind === "command_line" && <span className="line2">{t("not recorded by the dashboard (older import)")}</span>}</td>
                      <td>
                        <div className="row-actions">
                          {h.product && h.status !== "running" && h.status !== "queued" && (
                            <button type="button" className="btn-sm" disabled={!canAct} onClick={() => act(
                              () => apiSend<{ queued: unknown[]; skipped: { reason: string }[] }>("POST", h.kind === "job" ? `/admin/imports/${h.id}/rerun` : `/admin/imports/rerun-product/${h.product}`),
                              (r) => (r.queued.length ? t("Import queued.") : r.skipped.map((s) => s.reason).join("; ")),
                            )}>{t("Run again")}</button>
                          )}
                          {h.kind === "job" && h.status !== "running" && (
                            <button type="button" className="btn-sm" disabled={!canAct} onClick={() => act(() => apiSend("DELETE", `/admin/imports/${h.id}`))}>{t("Delete")}</button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="detail">
                        <td />
                        <td colSpan={6}>
                          <ul className="check-list" style={{ marginTop: 0 }}>
                            {Object.entries(h.results ?? {}).map(([v, r]) => (
                              <li key={v}>
                                <span className={`mark ${r.action === "failed" ? "fail" : "ok"}`} aria-hidden="true">{r.action === "failed" ? "✗" : r.action === "skipped" ? "–" : "✓"}</span>
                                <span><strong>{v}</strong>: {t(r.action)}{r.version ? ` · v${r.version}` : ""}{r.months ? ` · ${t("{n} months", { n: r.months })}` : ""}{r.detail ? ` — ${r.detail}` : ""}</span>
                              </li>
                            ))}
                            {Object.keys(h.results ?? {}).length === 0 && <li><span /> <span className="muted">{t("No results yet.")}</span></li>}
                          </ul>
                          <p className="small muted" style={{ margin: "8px 0 0" }}>{t("Requested by: {who}", { who: t(h.requested_by || "—") })}</p>
                          {h.kind === "job" && canAct && (
                            logs[k] ? <pre className="log">{logs[k].join("\n") || t("The log is empty.")}</pre>
                              : <button type="button" className="btn-sm" style={{ marginTop: 8 }} onClick={() => apiGet<{ lines: string[] }>(`/admin/imports/${h.id}/log`).then((r) => setLogs((m) => ({ ...m, [k]: r.lines }))).catch((e) => setLogs((m) => ({ ...m, [k]: [String(e.message)] })))}>{t("Show log")}</button>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {hist && hist.items.length === 0 && <tr><td colSpan={7} className="muted">{t("No imports match.")}</td></tr>}
            </tbody>
          </table>
        </div>
        {hist && (
          <div className="pager">
            <span>{hist.total ? t("Showing {a}–{b} of {n}", { a: (hist.page - 1) * hist.per_page + 1, b: Math.min(hist.total, hist.page * hist.per_page), n: hist.total }) : ""}</span>
            <span className="row" style={{ gap: 6 }}>
              <button type="button" className="btn-sm" disabled={hist.page <= 1} onClick={() => setQuery({ ...query, page: query.page - 1 })}>{t("Previous page")}</button>
              <button type="button" className="btn-sm" disabled={hist.page >= pages} onClick={() => setQuery({ ...query, page: query.page + 1 })}>{t("Next page")}</button>
            </span>
          </div>
        )}
      </Panel>
    </section>
  );
}

function JobPill({ status }: { status: HistoryItem["status"] }) {
  const { t } = useI18n();
  const cls = status === "done" ? "ok" : status === "failed" ? "fail" : "info";
  const label = { queued: "Queued", running: "Running", done: "Done", failed: "Failed" }[status];
  return <span className={`pill ${cls}`}>{t(label)}</span>;
}

// ---- 3. In the database ----------------------------------------------------------------------

const DB_TABS = [
  { id: "all", label: "All" },
  { id: "real", label: "Real NASA data" },
  { id: "stand_in", label: "Stand-in data" },
  { id: "nothing", label: "Nothing stored" },
] as const;

type SortKey = "name" | "kind" | "first_month" | "months" | "res_deg" | "size_bytes" | "imported_at" | "stored_days" | "compare";

function DatabaseSection({ db }: { db: Db | null }) {
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<(typeof DB_TABS)[number]["id"]>("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "name", dir: 1 });

  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const list = (db?.rows ?? []).filter((r) =>
      (tab === "all" || (tab === "real" ? r.kind === "real" : tab === "stand_in" ? r.kind === "test" || r.kind === "synthetic" : r.kind === null)) &&
      (!ql || [r.name, r.variable, r.product_title ?? "", r.archive ?? ""].some((s) => s.toLowerCase().includes(ql))),
    );
    const val = (r: DbRow): string | number => {
      const v = r[sort.key as keyof DbRow];
      return v === null || v === undefined ? (sort.dir === 1 ? "￿" : "") : (v as string | number);
    };
    return [...list].sort((a, b) => (val(a) < val(b) ? -sort.dir : val(a) > val(b) ? sort.dir : 0));
  }, [db, tab, q, sort]);

  const head = (key: SortKey, label: string) => (
    <th scope="col" aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort" onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : 1 }))}>
        {t(label)} <span aria-hidden="true">{sort.key === key ? (sort.dir === 1 ? "↑" : "↓") : ""}</span>
      </button>
    </th>
  );
  const c = db?.counts;

  return (
    <section className="dash-section" aria-labelledby="db-h">
      <Panel as="div">
        <h2 id="db-h"><Icon d={DB} /> {t("3. In the database")}</h2>
        <p className="sub">{t("What each variable holds, the period it covers, and how long it has been stored.")}</p>
        <div className="table-tools">
          <div className="chip-list" role="group" aria-label={t("Show variables")}>
            {DB_TABS.map((x) => (
              <button key={x.id} type="button" className="chip btn-sm" aria-pressed={tab === x.id} onClick={() => setTab(x.id)}>
                {t(x.label)} ({c ? c[x.id] : 0})
              </button>
            ))}
          </div>
          <input type="search" aria-label={t("Filter by name or source")} placeholder={t("Filter by name or source")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="dash-scroll">
          <table className="dash">
            <thead>
              <tr>
                {head("name", "Variable")}
                {head("kind", "Data")}
                {head("first_month", "Covers")}
                {head("months", "Months")}
                {head("res_deg", "Grid")}
                {head("size_bytes", "Size")}
                {head("imported_at", "Imported")}
                {head("stored_days", "Stored for")}
                {head("compare", "Compared with NASA")}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.variable}>
                  <td><strong>{r.name}</strong><span className="line2">{r.variable}</span></td>
                  <td>
                    {r.kind === "real" ? <span className="pill ok">{t("Real NASA data")}</span> : r.kind === "test" ? <span className="pill info">{t("Test box only")}</span> : r.kind === "synthetic" ? <span className="pill info">{t("Synthetic (for tests)")}</span> : <span className="pill">{t("Nothing stored")}</span>}
                    <span className="line2">{r.archive} · {r.product_title}{r.version ? ` · v${r.version}` : ""}</span>
                  </td>
                  <td className="num">{r.first_month ? `${r.first_month} ${t("to")} ${r.last_month}` : "—"}</td>
                  <td className="num">{r.months ?? "—"}{r.months ? <span className="line2">{t("{n} years", { n: (r.months / 12).toFixed(1) })}</span> : null}</td>
                  <td className="num">{r.res_deg ? `${r.res_deg}°` : "—"}</td>
                  <td className="num">{fmtBytes(r.size_bytes)}{r.download_bytes ? <span className="line2">{t("{s} downloaded", { s: fmtBytes(r.download_bytes) })}</span> : null}</td>
                  <td className="num">{fmtWhen(r.imported_at, lang)}</td>
                  <td className="num">{r.stored_days !== undefined ? t("{n} days", { n: r.stored_days }) : "—"}</td>
                  <td>
                    {r.compare === "up_to_date" ? <span className="pill ok">{t("Up to date")}</span>
                      : r.compare === "newer" ? <><span className="pill warn">{t("{n} newer months at NASA", { n: r.newer_months ?? 0 })}</span><span className="line2">{t("NASA has data to {m}", { m: r.nasa_last_month ?? "" })}</span></>
                      : r.compare === "stand_in" ? <span className="muted">{t("not real data")}</span>
                      : r.kind ? <span className="muted">{t("not checked")}</span> : "—"}
                  </td>
                </tr>
              ))}
              {db && rows.length === 0 && <tr><td colSpan={9} className="muted">{t("No variables match.")}</td></tr>}
            </tbody>
          </table>
        </div>
        {db && <p className="hint">{t("Showing {a} of {b} variables. Click a column title to sort; click again to reverse.", { a: rows.length, b: db.rows.length })}</p>}
      </Panel>
    </section>
  );
}
