import { recall, remember, signalOffline } from "./offline";

// Thin client for the MegavirTrace API (proxied at /api).  Every number shown comes from these
// responses; the page never computes statistics itself.

export type Region = { place?: string; bbox?: number[]; name?: string };

export type Variable = {
  id: string;
  name: string;
  theme: string;
  units: string;
  domain: string;
  agg: string;
  definition: string;
  why_it_can_trend: string;
  caveat: string;
  source_badge: string;
  year_units?: string | null;
  default_mode?: string;
  i18n?: Record<string, Record<string, unknown>>;
  dataset_info: { product: string; title: string; archive: string; doi: string | null; paper_doi: string | null; citation: string; native_grid: string; record_start: string; cadence: string };
  data: null | { id: number; kind: "real" | "test" | "synthetic"; bbox: number[]; first_month: string; last_month: string; res_deg: number; validation?: Record<string, unknown> };
};

export type Catalog = { themes: string[]; variables: Variable[]; planned: { id: string; name: string; theme: string; dataset_info: { product: string; doi: string } }[] };

export type Place = { id: string; name: string; kind: string; context: string; lat: number; lon: number; bbox: number[]; population: number; geometry?: GeoJSON.Geometry | null };

export type Verdict = { status: string; direction?: string; headline: string; sentences: string[]; caveats: string[]; shown: Record<string, string>; lang: string };

export type CellMap = {
  res: number; lat: (number | null)[]; lon: (number | null)[]; frac: (number | null)[]; slope_per_decade: (number | null)[];
  p: (number | null)[]; q: (number | null)[]; passes: boolean[]; alpha_fdr: number; n_cells: number; n_pass: number;
  n_raw_significant: number; basis: string; caveat: string;
} | { skipped: string };

export type TrendResult = {
  id: string; kind: "trend"; request: Record<string, unknown>; variable: Variable; units: string;
  region: { id: string | null; name: string; kind: string; bbox: number[]; context: string; geometry?: GeoJSON.Geometry | null };
  series: { mode: string; season: string | null; labels: string[]; t: (number | null)[]; values: (number | null)[]; plot_values: (number | null)[]; trend_line: (number | null)[]; per_year: number };
  monthly: { labels: string[]; values: (number | null)[]; coverage: (number | null)[]; units: string };
  stats: Stats; verdict: Verdict; cell_map: CellMap | null;
  data: { id: number; kind: string; first_month: string; last_month: string; res_deg: number; bbox: number[] };
  provenance: Provenance; compute_ms: number;
};

export type Stats = {
  n: number; per_year: number; seasonal_test: boolean; first: number; last: number; significant: boolean; agree: boolean;
  direction: string; years_needed: number | string; years_more: number | string; effect_ratio: number; effect_label: string;
  ols: { slope: number; ci_low: number; ci_high: number; p: number; r1: number; r1_raw: number; n_eff: number; testable: boolean; resid_sd: number };
  mk: { S: number; Z: number; p: number; tau: number; variance_ratio: number };
  sen: { slope: number; ci_low: number; ci_high: number };
  robustness: { fragile: boolean; checks: { check: string; slope: number; keeps_sign: boolean }[] };
  unusual: { label: string; departure: number; sd_units: number }[];
  turning: null | { at: number; slope_before: number; slope_after: number; preferred: boolean };
  acceleration: null | { tested: boolean; significant: boolean; kind: string | null; p?: number; slope_early?: number; slope_late?: number; split?: number; reason?: string };
  per_decade: { sen: number; sen_low: number; sen_high: number; ols: number; ols_low: number; ols_high: number };
};

export type Provenance = { product: string; title: string; archive: string; doi: string | null; paper_doi: string | null; citation: string; source_badge: string; grid: string; data_version: number; data_kind: string; engine_version: string; fingerprint: string };

export type CompareResult = {
  id: string; kind: "compare"; variable: Variable; units: string;
  region_a: { name: string; bbox: number[]; geometry?: GeoJSON.Geometry | null }; region_b: { name: string; bbox: number[]; geometry?: GeoJSON.Geometry | null };
  comparison: { labels: string[]; t: number[]; a: number[]; b: number[]; diff: number[]; correlation: number; opposite: boolean;
    difference: { slope_per_decade: number; ci_low_per_decade: number; ci_high_per_decade: number; p: number; significant: boolean; min_detectable_per_decade: number };
    stats_a: Stats; stats_b: Stats; stats_diff: Stats };
  verdict: Verdict; data: { kind: string }; provenance: Provenance;
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `Request failed (${r.status})`;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(msg, r.status);
  }
  return r.json() as Promise<T>;
}

// Import dashboard: actions from another computer need the administrator token.  It is kept for
// this browser tab only (sessionStorage, never a cookie) and sent only to /admin requests.
const ADMIN_KEY = "mt-admin-token";

export function adminToken(): string | null {
  try {
    return sessionStorage.getItem(ADMIN_KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(ADMIN_KEY, token);
    else sessionStorage.removeItem(ADMIN_KEY);
  } catch {
    /* private mode */
  }
}

function adminHeaders(path: string): Record<string, string> {
  const token = path.startsWith("/admin") ? adminToken() : null;
  return token ? { "X-Admin-Token": token } : {};
}

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>, signal?: AbortSignal): Promise<T> {
  const qs = params
    ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString()
    : "";
  return handle<T>(await fetch(`/api${path}${qs}`, { signal, headers: adminHeaders(path) }));
}

/** Requests that change something on the server (never answered from the offline copy). */
export async function apiSend<T>(method: "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...adminHeaders(path) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return handle<T>(await fetch(`/api${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined }));
}

export async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  } catch (err) {
    // no connection: fall back to the copy kept on this device, if any
    if ((err as Error).name !== "AbortError") {
      const saved = recall<T>(path, body);
      if (saved) {
        signalOffline();
        return saved;
      }
    }
    throw err;
  }
  const value = await handle<T>(response);
  remember(path, body, value);
  return value;
}

export const exportUrl = (id: string, format: string) => `/api/reports/${id}/export?format=${format}`;

// ---- detective cases ---------------------------------------------------------------------

export type CaseChart = {
  kind: "month" | "trend" | "compare";
  title?: string;
  labels: string[];
  t?: (number | null)[];
  series: { key: string; label?: string; values: (number | null)[] }[];
  highlight: number[];
  units: string;
  mean?: number;
  trend?: { line: (number | null)[]; low: number; high: number };
  per_decade_label?: string;
};
export type CaseVariable = { id: string; name: string; units: string; product: string; doi: string | null };
export type CaseStep = {
  kind: "month" | "trend" | "compare";
  title: string;
  look: string;
  variable: CaseVariable;
  explore: Record<string, string | number>;
  finding?: string;
  chart?: CaseChart;
  region?: string;
  analysis_id?: string | null;
  error?: string;
};
export type CaseInfo = {
  id: string; title: string; theme: string; kind: "event" | "change"; when: string; where: string;
  story: string; question: string; takeaway: string; skills: string[]; n_steps: number;
  variables: CaseVariable[]; regions: { label: string; bbox: number[] }[]; data_kind: string;
};
export type CaseSummary = CaseInfo & { evidence: { finding: string; title: string; chart: CaseChart } | null };
export type CaseDetail = CaseInfo & { steps: CaseStep[]; key: number; lang: string };
