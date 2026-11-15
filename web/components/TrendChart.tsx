"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fmt, fmtSigned, niceTicks, tickLabel } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { FullscreenButton, useFullHeight } from "./Panel";

export type ChartSeries = {
  key: string;
  label: string;
  color: string; // CSS var
  values: (number | null)[];
  markers?: boolean;
  connect?: boolean; // draw through missing values (sparse sample years)
};

type Props = {
  title: string;
  labels: string[];
  t: (number | null)[];
  series: ChartSeries[];
  units: string;
  trend?: { line: (number | null)[]; slopeLow: number; slopeHigh: number; label: string } | null;
  height?: number;
  zeroLine?: boolean;
};

const PAD = { left: 52, right: 16, top: 12, bottom: 30 };

export default function TrendChart({ title, labels, t, series, units, trend, height: baseHeight = 300, zeroLine }: Props) {
  const height = useFullHeight(baseHeight);
  const { t: tr } = useI18n();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver((e) => setWidth(Math.max(280, e[0].contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const idx = useMemo(() => t.map((v, i) => (v === null ? -1 : i)).filter((i) => i >= 0), [t]);

  const geom = useMemo(() => {
    const xs = idx.map((i) => t[i] as number);
    const ys: number[] = [];
    for (const s of series) for (const i of idx) if (s.values[i] !== null) ys.push(s.values[i] as number);
    let fan: { x0: number; x1: number; lo0: number; lo1: number; hi0: number; hi1: number } | null = null;
    if (trend) {
      const pts = idx.filter((i) => trend.line[i] !== null);
      if (pts.length > 1) {
        const x0 = t[pts[0]] as number;
        const x1 = t[pts[pts.length - 1]] as number;
        const xm = (x0 + x1) / 2;
        const ym = ((trend.line[pts[0]] as number) + (trend.line[pts[pts.length - 1]] as number)) / 2;
        if (Number.isFinite(trend.slopeLow) && Number.isFinite(trend.slopeHigh)) {
          fan = {
            x0, x1,
            lo0: ym + trend.slopeLow * (x0 - xm), lo1: ym + trend.slopeLow * (x1 - xm),
            hi0: ym + trend.slopeHigh * (x0 - xm), hi1: ym + trend.slopeHigh * (x1 - xm),
          };
          ys.push(fan.lo0, fan.lo1, fan.hi0, fan.hi1);
        }
        for (const i of pts) ys.push(trend.line[i] as number);
      }
    }
    if (zeroLine) ys.push(0);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    let ymin = Math.min(...ys), ymax = Math.max(...ys);
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    const yt = niceTicks(ymin, ymax, 5);
    const y0 = Math.min(ymin, yt[0] ?? ymin), y1 = Math.max(ymax, yt[yt.length - 1] ?? ymax);
    const pw = width - PAD.left - PAD.right, ph = height - PAD.top - PAD.bottom;
    const X = (v: number) => PAD.left + ((v - xmin) / (xmax - xmin || 1)) * pw;
    const Y = (v: number) => PAD.top + (1 - (v - y0) / (y1 - y0 || 1)) * ph;
    const xt = niceTicks(xmin, xmax, Math.max(2, Math.floor(pw / 90))).filter((v) => v >= xmin && v <= xmax);
    return { X, Y, yt, xt, pw, ph, fan };
  }, [idx, t, series, trend, width, height, zeroLine]);

  if (idx.length === 0) return <p className="muted">No values to plot.</p>;
  const { X, Y, yt, xt, fan } = geom;

  const path = (vals: (number | null)[], connect = false) => {
    let d = "";
    let pen = false;
    for (const i of idx) {
      const v = vals[i];
      if (v === null) { if (!connect) pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(t[i] as number).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };

  const nearest = (clientX: number) => {
    const rect = wrap.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = clientX - rect.left;
    let best = idx[0], bd = Infinity;
    for (const i of idx) {
      const d = Math.abs(X(t[i] as number) - x);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(e.key)) return;
    e.preventDefault();
    if (e.key === "Escape") return setHover(null);
    const pos = hover === null ? -1 : idx.indexOf(hover);
    const next = e.key === "Home" ? 0 : e.key === "End" ? idx.length - 1 : e.key === "ArrowLeft" ? Math.max(0, pos - 1) : Math.min(idx.length - 1, pos + 1);
    setHover(idx[next]);
  };

  const many = idx.length > 70;
  const hx = hover !== null ? X(t[hover] as number) : 0;

  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="row" style={{ justifyContent: "space-between" }}>
        <strong>{title}</strong>
        <span className="row" style={{ gap: 8 }}>
          <FullscreenButton />
          <button type="button" onClick={() => setShowTable((s) => !s)} aria-pressed={showTable}>
            {showTable ? tr("Show chart") : tr("Show table")}
          </button>
        </span>
      </figcaption>
      {series.length + (trend ? 1 : 0) >= 2 && !showTable && (
        <div className="chart-legend" aria-hidden="true">
          {series.map((s) => (
            <span className="key" key={s.key}><i style={{ background: s.color }} />{s.label}</span>
          ))}
          {trend && (
            <>
              <span className="key"><i style={{ background: "var(--series-2)" }} />{trend.label}</span>
              {fan && <span className="key"><i className="band" style={{ background: "var(--series-2)" }} />{tr("95% range of the trend")}</span>}
            </>
          )}
        </div>
      )}
      {showTable ? (
        <div className="table-scroll" tabIndex={0} role="region" aria-label={`${title} as a table`}>
          <table className="data">
            <thead>
              <tr>
                <th scope="col">{tr("Period")}</th>
                {series.map((s) => <th scope="col" key={s.key}>{s.label} ({units})</th>)}
                {trend && <th scope="col">{tr("Trend line")} ({units})</th>}
              </tr>
            </thead>
            <tbody>
              {idx.map((i) => (
                <tr key={i}>
                  <td>{labels[i]}</td>
                  {series.map((s) => <td key={s.key}>{fmt(s.values[i], 3)}</td>)}
                  {trend && <td>{fmt(trend.line[i], 3)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          ref={wrap}
          className="chart-wrap"
          tabIndex={0}
          role="img"
          aria-label={tr("{title}. {n} values from {a} to {b}, in {units}. Use the left and right arrow keys to read values, or open the table.", { title, n: idx.length, a: labels[idx[0]], b: labels[idx[idx.length - 1]], units })}
          onMouseMove={(e) => setHover(nearest(e.clientX))}
          onMouseLeave={() => setHover(null)}
          onKeyDown={onKey}
          onBlur={() => setHover(null)}
        >
          <svg width={width} height={height} style={{ display: "block" }}>
            {yt.map((v) => (
              <g key={v}>
                <line x1={PAD.left} x2={width - PAD.right} y1={Y(v)} y2={Y(v)} stroke="var(--grid)" strokeWidth={1} />
                <text x={PAD.left - 6} y={Y(v) + 4} textAnchor="end" fontSize={11} fill="var(--text-secondary)" className="tabular">{tickLabel(v)}</text>
              </g>
            ))}
            {zeroLine && <line x1={PAD.left} x2={width - PAD.right} y1={Y(0)} y2={Y(0)} stroke="var(--axis)" strokeWidth={1} />}
            <line x1={PAD.left} x2={width - PAD.right} y1={height - PAD.bottom} y2={height - PAD.bottom} stroke="var(--axis)" strokeWidth={1} />
            {xt.map((v) => (
              <text key={v} x={X(v)} y={height - PAD.bottom + 16} textAnchor="middle" fontSize={11} fill="var(--text-secondary)" className="tabular">{Math.round(v)}</text>
            ))}
            <text x={PAD.left} y={PAD.top - 2} fontSize={11} fill="var(--text-secondary)">{units}</text>
            {fan && (
              <polygon
                points={`${X(fan.x0)},${Y(fan.lo0)} ${X(fan.x1)},${Y(fan.lo1)} ${X(fan.x1)},${Y(fan.hi1)} ${X(fan.x0)},${Y(fan.hi0)}`}
                fill="var(--series-2)" opacity={0.1}
              />
            )}
            {series.map((s) => (
              <g key={s.key}>
                <path d={path(s.values, s.connect)} fill="none" stroke={s.color} strokeWidth={many ? 1.25 : 2} strokeLinejoin="round" strokeLinecap="round" />
                {s.markers !== false && (!many || s.connect) && idx.map((i) => s.values[i] !== null && (
                  <circle key={i} cx={X(t[i] as number)} cy={Y(s.values[i] as number)} r={4} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
                ))}
              </g>
            ))}
            {trend && <path d={path(trend.line)} fill="none" stroke="var(--series-2)" strokeWidth={2} strokeLinecap="round" />}
            {hover !== null && (
              <g>
                <line x1={hx} x2={hx} y1={PAD.top} y2={height - PAD.bottom} stroke="var(--axis)" strokeWidth={1} />
                {series.map((s) => s.values[hover] !== null && (
                  <circle key={s.key} cx={hx} cy={Y(s.values[hover] as number)} r={5} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
                ))}
              </g>
            )}
          </svg>
          {hover !== null && (
            <div className="tooltip" style={{ left: Math.min(hx + 12, width - 190), top: 8 }} aria-hidden="true">
              <div className="t-label">{labels[hover]}</div>
              {series.map((s) => (
                <div key={s.key} className="tabular">
                  <span className="key"><i style={{ background: s.color }} /></span> {s.label}: <strong>{fmt(s.values[hover], 3)}</strong> {units}
                </div>
              ))}
              {trend && trend.line[hover] !== null && (
                <div className="tabular">Trend line: {fmtSigned(trend.line[hover], 3)} {units}</div>
              )}
            </div>
          )}
        </div>
      )}
      <p className="visually-hidden" aria-live="polite">
        {hover !== null && !showTable
          ? `${labels[hover]}: ` + series.map((s) => `${s.label} ${fmt(s.values[hover], 3)} ${units}`).join("; ")
          : ""}
      </p>
    </figure>
  );
}
