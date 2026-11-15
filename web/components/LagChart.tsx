"use client";

import { useEffect, useRef, useState } from "react";
import { fmt, fmtP } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { FullscreenButton, useFullHeight, ViewSwitch } from "./Panel";

// Correlation by lag: one series of columns (slot 1); the strongest link is marked in slot 2 and named
// in the legend, so identity never rests on colour alone.  Reference lines are solid hairlines.
export default function LagChart({ lags, r, p, n, best, rNeeded, labelA, labelB }: {
  lags: number[];
  r: (number | null)[];
  p: (number | null)[];
  n: number[];
  best: number;
  rNeeded: number | null;
  labelA: string;
  labelB: string;
}) {
  const { t } = useI18n();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver((e) => setWidth(Math.max(280, e[0].contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = useFullHeight(220, 200), L = 44, R = 12, T = 12, B = 34;
  const pw = width - L - R, ph = H - T - B;
  const vals = r.map((x) => (x === null ? 0 : x));
  const lim = Math.max(0.2, ...vals.map(Math.abs), rNeeded ?? 0) * 1.1;
  const Y = (v: number) => T + (1 - (v + lim) / (2 * lim)) * ph;
  const slot = pw / lags.length;
  const bw = Math.min(24, Math.max(4, slot - 2));
  const X = (i: number) => L + i * slot + (slot - bw) / 2;
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim].map((v) => Math.round(v * 100) / 100);

  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="row" style={{ justifyContent: "space-between" }}>
        <strong>{t("How closely they move together at each lag")}</strong>
        <span className="row" style={{ gap: 8 }}>
          <FullscreenButton />
          <ViewSwitch table={table} onChange={setTable} />
        </span>
      </figcaption>
      {!table && (
        <div className="chart-legend" aria-hidden="true">
          <span className="key"><i style={{ background: "var(--series-1)", height: 10 }} />{t("correlation r at each lag")}</span>
          <span className="key"><i style={{ background: "var(--series-2)", height: 10 }} />{t("strongest link (lag {k})", { k: String(best) })}</span>
          {rNeeded !== null && <span className="key"><i style={{ background: "var(--text-secondary)", height: 1 }} />{t("|r| needed after the lag search (±{r})", { r: fmt(rNeeded, 2) })}</span>}
        </div>
      )}
      {table ? (
        <div className="table-scroll" tabIndex={0} role="region" aria-label={t("Correlation by lag as a table")}>
          <table className="data">
            <thead><tr><th scope="col">{t("Lag (months)")}</th><th scope="col">r</th><th scope="col">{t("p (single lag)")}</th><th scope="col">{t("Pairs")}</th></tr></thead>
            <tbody>{lags.map((k, i) => <tr key={k}><td>{k}</td><td>{fmt(r[i], 2)}</td><td>{fmtP(p[i])}</td><td>{n[i]}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div ref={wrap} className="chart-wrap" tabIndex={0} role="img"
          aria-label={`Correlation by lag from ${lags[0]} to ${lags[lags.length - 1]} months; strongest at lag ${best}, r ${fmt(r[lags.indexOf(best)], 2)}. Positive lags: ${labelB} follows ${labelA}. Open the table for every value.`}
          onMouseLeave={() => setHover(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") setHover((h) => Math.min(lags.length - 1, (h ?? -1) + 1));
            else if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? lags.length) - 1));
            else if (e.key === "Escape") setHover(null);
          }}>
          <svg width={width} height={H} style={{ display: "block" }}>
            {ticks.map((v) => (
              <g key={v}>
                <line x1={L} x2={width - R} y1={Y(v)} y2={Y(v)} stroke={v === 0 ? "var(--axis)" : "var(--grid)"} />
                <text x={L - 6} y={Y(v) + 4} textAnchor="end" fontSize={11} fill="var(--text-secondary)" className="tabular">{fmt(v, 2)}</text>
              </g>
            ))}
            {rNeeded !== null && [rNeeded, -rNeeded].map((v) => (
              <line key={v} x1={L} x2={width - R} y1={Y(v)} y2={Y(v)} stroke="var(--text-secondary)" strokeWidth={1} />
            ))}
            {lags.map((k, i) => {
              const v = r[i];
              if (v === null) return null;
              const y0 = Y(0), y1 = Y(v);
              const top = Math.min(y0, y1), h = Math.max(1, Math.abs(y1 - y0));
              return (
                <g key={k} onMouseEnter={() => setHover(i)}>
                  <rect x={L + i * slot} y={T} width={slot} height={ph} fill="transparent" />
                  <rect x={X(i)} y={top} width={bw} height={h} rx={2} fill={k === best ? "var(--series-2)" : "var(--series-1)"} opacity={hover === null || hover === i ? 1 : 0.6} />
                </g>
              );
            })}
            {lags.map((k, i) => (k % 3 === 0 ? (
              <text key={k} x={X(i) + bw / 2} y={H - B + 16} textAnchor="middle" fontSize={11} fill="var(--text-secondary)" className="tabular">{k}</text>
            ) : null))}
            <text x={width - R} y={H - 4} textAnchor="end" fontSize={11} fill="var(--text-secondary)">lag in months ({labelB} follows {labelA} →)</text>
          </svg>
          {hover !== null && r[hover] !== null && (
            <div className="tooltip" style={{ left: Math.min(X(hover) + 14, width - 200), top: 8 }} aria-hidden="true">
              <div className="t-label">Lag {lags[hover]} months</div>
              <div className="tabular">r = <strong>{fmt(r[hover], 2)}</strong> · {n[hover]} pairs</div>
            </div>
          )}
        </div>
      )}
      <p className="visually-hidden" aria-live="polite">{hover !== null && r[hover] !== null ? `Lag ${lags[hover]} months: r ${fmt(r[hover], 2)}` : ""}</p>
    </figure>
  );
}
