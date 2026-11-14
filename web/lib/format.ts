// Display formatting only (the verdict text itself is formatted on the server from templates).

const MINUS = "−";

export function fmt(x: number | null | undefined | string, sig = 2): string {
  if (x === null || x === undefined) return "—";
  if (typeof x === "string") return x === "inf" ? "∞" : x === "-inf" ? `${MINUS}∞` : x;
  if (!Number.isFinite(x)) return x > 0 ? "∞" : `${MINUS}∞`;
  if (x === 0) return "0";
  const mag = Math.floor(Math.log10(Math.abs(x)));
  const dec = Math.min(4, Math.max(0, sig - 1 - mag));
  const s = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  return (x < 0 ? MINUS : "") + s;
}

export function fmtSigned(x: number | null | undefined, sig = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return fmt(x, sig);
  const s = fmt(x, sig);
  return x > 0 ? "+" + s : s;
}

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "—";
  return p < 0.001 ? "< 0.001" : fmt(p, 2);
}

export function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (hi <= lo) hi = lo + 1;
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}

export function tickLabel(v: number): string {
  const a = Math.abs(v);
  if (a >= 10000) return (v < 0 ? MINUS : "") + (a / 1000).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "K";
  const s = a.toLocaleString("en-US", { maximumFractionDigits: 4 });
  return (v < 0 ? MINUS : "") + s;
}

export const MODE_LABEL: Record<string, string> = {
  annual: "Yearly values",
  season: "Seasonal values",
  monthly: "Monthly anomalies (seasonal cycle removed)",
  raw: "Raw monthly values",
};
