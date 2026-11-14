"use client";

import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MLMap } from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import type { CellMap } from "@/lib/api";
import { fmt, fmtSigned } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { divergingFor, isDark } from "@/lib/palette";

type Outline = { geometry?: GeoJSON.Geometry | null; bbox?: number[] | null; label?: string };

type Props = {
  outlines: Outline[];
  cells?: CellMap | null;
  variable?: string;
  units?: string;
  dataArea?: number[] | null; // bbox of test/synthetic data
  drawMode?: boolean;
  onBox?: (bbox: number[]) => void;
  height?: number;
  points?: { lat: number; lon: number; name: string }[];
};

// The worker is copied to /public by `npm run copy-worker` (bundlers cannot resolve it reliably).
if (typeof window !== "undefined") maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function bboxPolygon(b: number[]): GeoJSON.Polygon {
  const [w, s, e0, n] = b;
  const e = e0 < w ? e0 + 360 : e0;
  return { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] };
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
}

export default function EarthMap({ outlines, cells, variable = "", units = "", dataArea, drawMode, onBox, height, points }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [globe, setGlobe] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [hoverInfo, setHoverInfo] = useState<string>("");
  const [themeTick, setThemeTick] = useState(0);
  const drawStart = useRef<maplibregl.LngLat | null>(null);
  const { t } = useI18n();

  // ---- create the map once --------------------------------------------------------------
  useEffect(() => {
    if (!box.current || map.current) return;
    const m = new maplibregl.Map({
      container: box.current,
      style: {
        version: 8,
        sources: {
          world: { type: "geojson", data: "/world.json" },
          region: { type: "geojson", data: EMPTY },
          cells: { type: "geojson", data: EMPTY },
          area: { type: "geojson", data: EMPTY },
          draft: { type: "geojson", data: EMPTY },
          points: { type: "geojson", data: EMPTY },
        },
        layers: [
          { id: "sea", type: "background", paint: { "background-color": cssVar("--sea") } },
          { id: "land", type: "fill", source: "world", paint: { "fill-color": cssVar("--land") } },
          { id: "cells", type: "fill", source: "cells", paint: { "fill-color": ["get", "color"], "fill-opacity": ["get", "opacity"], "fill-antialias": false } },
          { id: "borders", type: "line", source: "world", paint: { "line-color": cssVar("--text-secondary"), "line-width": 0.5, "line-opacity": 0.6 } },
          { id: "area", type: "line", source: "area", paint: { "line-color": cssVar("--text-secondary"), "line-width": 1.5, "line-dasharray": [2, 2] } },
          { id: "region-line", type: "line", source: "region", paint: { "line-color": cssVar("--text-primary"), "line-width": 2 } },
          { id: "draft", type: "line", source: "draft", paint: { "line-color": cssVar("--series-2"), "line-width": 2 } },
          {
            id: "points", type: "circle", source: "points",
            paint: { "circle-radius": 5, "circle-color": cssVar("--series-2"), "circle-stroke-color": cssVar("--surface-1"), "circle-stroke-width": 2 },
          },
        ],
      },
      center: [0, 20],
      zoom: 0,
      minZoom: -2,
      attributionControl: false,
      renderWorldCopies: false,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "Outlines: Natural Earth" }));
    m.getCanvas().setAttribute("aria-label", "Map. Drag or use the arrow keys to move, plus and minus to zoom.");
    m.on("load", () => setReady(true));
    map.current = m;
    const onTheme = () => setThemeTick((x) => x + 1);
    window.addEventListener("mt-theme", onTheme);
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", onTheme);
    return () => {
      window.removeEventListener("mt-theme", onTheme);
      mq?.removeEventListener?.("change", onTheme);
      m.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    map.current?.getCanvas().setAttribute("aria-label", t("Map. Drag or use the arrow keys to move, plus and minus to zoom."));
  }, [t, ready]);

  // ---- theme colours -------------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    m.setPaintProperty("sea", "background-color", cssVar("--sea"));
    m.setPaintProperty("land", "fill-color", cssVar("--land"));
    m.setPaintProperty("borders", "line-color", cssVar("--text-secondary"));
    m.setPaintProperty("region-line", "line-color", cssVar("--text-primary"));
    m.setPaintProperty("area", "line-color", cssVar("--text-secondary"));
  }, [ready, themeTick]);

  // ---- outlines and the data area ---------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const feats: GeoJSON.Feature[] = outlines
      .map((o) => (o.geometry ? o.geometry : o.bbox ? bboxPolygon(o.bbox) : null))
      .filter(Boolean)
      .map((g) => ({ type: "Feature", properties: {}, geometry: g as GeoJSON.Geometry }));
    (m.getSource("region") as GeoJSONSource).setData({ type: "FeatureCollection", features: feats });
    (m.getSource("area") as GeoJSONSource).setData(
      dataArea ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: bboxPolygon(dataArea) }] } : EMPTY,
    );
    const bbs = outlines.map((o) => o.bbox).filter(Boolean) as number[][];
    if (bbs.length) {
      let w = Math.min(...bbs.map((b) => b[0])), s = Math.min(...bbs.map((b) => b[1]));
      let e = Math.max(...bbs.map((b) => (b[2] < b[0] ? b[2] + 360 : b[2]))), n = Math.max(...bbs.map((b) => b[3]));
      if (e - w > 300) { w = -180; e = 180; }
      s = Math.max(s, -85); n = Math.min(n, 85);
      m.resize();
      m.fitBounds([[w, s], [e, n]], { padding: 30, duration: reducedMotion() ? 0 : 600, maxZoom: 7 });
    }
  }, [outlines, dataArea, ready]);

  // ---- points (GLOBE sites) ----------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    (m.getSource("points") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: (points ?? []).map((pt) => ({ type: "Feature", properties: { name: pt.name }, geometry: { type: "Point", coordinates: [pt.lon, pt.lat] } })),
    });
  }, [points, ready]);

  // ---- cells -------------------------------------------------------------------------------
  const ramp = useCallback(() => divergingFor(variable, isDark()), [variable]);
  const scaleMax = cells && !("skipped" in cells)
    ? (() => {
        const v = cells.slope_per_decade.filter((x): x is number => x !== null).map(Math.abs).sort((a, b) => a - b);
        return v.length ? v[Math.min(v.length - 1, Math.floor(v.length * 0.98))] || v[v.length - 1] || 1 : 1;
      })()
    : 1;

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const src = m.getSource("cells") as GeoJSONSource;
    if (!cells || "skipped" in cells) { src.setData(EMPTY); return; }
    const r = ramp();
    const h = cells.res / 2;
    const feats: GeoJSON.Feature[] = [];
    for (let i = 0; i < cells.lat.length; i++) {
      const s = cells.slope_per_decade[i], la = cells.lat[i], lo = cells.lon[i];
      if (s === null || la === null || lo === null) continue;
      const k = Math.min(3, Math.floor((Math.abs(s) / (scaleMax || 1)) * 4));
      const color = Math.abs(s) < 1e-12 ? r.mid : s > 0 ? r.positive[k] : r.negative[k];
      feats.push({
        type: "Feature",
        properties: { color, opacity: showRaw || cells.passes[i] ? 0.85 : 0.22, s, q: cells.q[i], pass: cells.passes[i] },
        geometry: { type: "Polygon", coordinates: [[[lo - h, la - h], [lo + h, la - h], [lo + h, la + h], [lo - h, la + h], [lo - h, la - h]]] },
      });
    }
    src.setData({ type: "FeatureCollection", features: feats });
  }, [cells, ready, showRaw, ramp, scaleMax, themeTick]);

  // ---- cell hover ------------------------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const move = (e: maplibregl.MapLayerMouseEvent) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as { s: number; q: number | null; pass: boolean };
      setHoverInfo(`${fmtSigned(Number(p.s), 2)} ${units} per decade · q = ${p.q === null ? "—" : fmt(Number(p.q), 2)} · ${String(p.pass) === "true" ? "passes" : "does not pass"} the false-discovery test`);
      m.getCanvas().style.cursor = "crosshair";
    };
    const leave = () => { setHoverInfo(""); m.getCanvas().style.cursor = ""; };
    m.on("mousemove", "cells", move);
    m.on("mouseleave", "cells", leave);
    return () => { m.off("mousemove", "cells", move); m.off("mouseleave", "cells", leave); };
  }, [ready, units]);

  // ---- draw a box ---------------------------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (!drawMode) {
      m.dragPan.enable();
      (m.getSource("draft") as GeoJSONSource).setData(EMPTY);
      return;
    }
    m.dragPan.disable();
    const toBox = (a: maplibregl.LngLat, b: maplibregl.LngLat) => [
      Math.max(-180, Math.min(a.lng, b.lng)), Math.max(-90, Math.min(a.lat, b.lat)),
      Math.min(180, Math.max(a.lng, b.lng)), Math.min(90, Math.max(a.lat, b.lat)),
    ].map((v) => Math.round(v * 100) / 100);
    const down = (e: maplibregl.MapMouseEvent) => { drawStart.current = e.lngLat; };
    const move = (e: maplibregl.MapMouseEvent) => {
      if (!drawStart.current) return;
      (m.getSource("draft") as GeoJSONSource).setData({ type: "Feature", properties: {}, geometry: bboxPolygon(toBox(drawStart.current, e.lngLat)) });
    };
    const up = (e: maplibregl.MapMouseEvent) => {
      if (!drawStart.current) return;
      const b = toBox(drawStart.current, e.lngLat);
      drawStart.current = null;
      if (b[2] - b[0] >= 0.5 && b[3] - b[1] >= 0.5) onBox?.(b);
    };
    m.on("mousedown", down);
    m.on("mousemove", move);
    m.on("mouseup", up);
    return () => { m.off("mousedown", down); m.off("mousemove", move); m.off("mouseup", up); m.dragPan.enable(); };
  }, [drawMode, ready, onBox]);

  // ---- 2D <-> 3D -------------------------------------------------------------------------------------
  function toggleProjection() {
    const m = map.current;
    if (!m) return;
    const next = !globe;
    setGlobe(next);
    const apply = () => m.setProjection({ type: next ? "globe" : "mercator" });
    const z = m.getZoom();
    const c = m.getCenter();
    // a whole-world flat view sits below zoom 0; the globe needs ~1.5 to fill the box
    const target = next ? Math.max(z, 1.5) : z < 1.6 ? Math.min(z, 0) : z;
    if (reducedMotion()) { apply(); m.jumpTo({ zoom: target, center: c }); return; }
    m.easeTo({ zoom: Math.max(-1, z - 1), duration: 300 });
    m.once("moveend", () => {
      apply();
      m.easeTo({ zoom: target, center: c, duration: 600 });
    });
  }

  const r = ramp();
  const hasCells = cells && !("skipped" in cells);
  return (
    <div>
      <div className="map-tools">
        <div className="segmented" role="group" aria-label={t("Map view")}>
          <button type="button" aria-pressed={!globe} onClick={() => globe && toggleProjection()}>{t("Flat map (2D)")}</button>
          <button type="button" aria-pressed={globe} onClick={() => !globe && toggleProjection()}>{t("Globe (3D)")}</button>
        </div>
        {hasCells && (
          <label className="row small">
            <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
            {t("Show raw view (no false-discovery fading)")}
          </label>
        )}
      </div>
      <div ref={box} className="map-box" style={height ? { height } : undefined} />
      {hasCells && (
        <div className="stack" style={{ gap: 6, marginTop: 8 }}>
          <div className="legend-ramp" aria-label={t("Colour scale")}>
            <span>{fmtSigned(-scaleMax, 2)}</span>
            <span className="swatches" aria-hidden="true">
              {[...r.negative].reverse().map((c) => <span key={c} style={{ background: c }} />)}
              <span style={{ background: r.mid }} />
              {r.positive.map((c) => <span key={c} style={{ background: c }} />)}
            </span>
            <span>{fmtSigned(scaleMax, 2)} {t("{units} per decade", { units })}</span>
          </div>
          <p className="small muted" style={{ margin: 0 }}>
            {t("{n} of {m} cells pass the false-discovery test (faded cells do not; q ≤ {q}, tuned for neighbouring cells that move together, Wilks 2016).", {
              n: (cells as Exclude<CellMap, { skipped: string }>).n_pass,
              m: (cells as Exclude<CellMap, { skipped: string }>).n_cells,
              q: (cells as Exclude<CellMap, { skipped: string }>).alpha_fdr,
            })}{" "}
            {t((cells as Exclude<CellMap, { skipped: string }>).caveat)} {t("Based on {basis}.", { basis: (cells as Exclude<CellMap, { skipped: string }>).basis })}
          </p>
          <p className="small" aria-live="polite" style={{ margin: 0, minHeight: "1.3em" }}>{hoverInfo}</p>
        </div>
      )}
      {cells && "skipped" in cells && <p className="small muted">{t("Cell map:")} {cells.skipped}.</p>}
      {dataArea && <p className="small muted" style={{ margin: "4px 0 0" }}>{t("Dashed box: the only area this variable has data for so far.")}</p>}
    </div>
  );
}
