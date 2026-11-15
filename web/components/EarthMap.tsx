"use client";

import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LayerSpecification, Map as MLMap, StyleSpecification } from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiPost, type CellMap } from "@/lib/api";
import { fmt, fmtSigned } from "@/lib/format";
import { changeUnit, useI18n } from "@/lib/i18n";
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
  /** the analysis request, to fetch full detail of the area in view when the region's map is merged */
  detailRequest?: Record<string, unknown> | null;
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

// ---- base map --------------------------------------------------------------------------------
// The detailed street map (OpenStreetMap data: roads, places, parks, buildings) comes through our
// API, which relays and keeps the files (src/megavir/api/basemap.py).  Without it (offline, or
// turned off on the server) the map falls back to the built-in country outlines.

type Theme = "light" | "dark";
const baseStyles = new Map<Theme, Promise<StyleSpecification | null>>();
let detailedBroken = false; // tiles failed this visit: stay with the outlines

function loadBase(theme: Theme): Promise<StyleSpecification | null> {
  if (detailedBroken || (typeof navigator !== "undefined" && navigator.onLine === false)) return Promise.resolve(null);
  let style = baseStyles.get(theme);
  if (!style) {
    const ctl = new AbortController();
    const timer = window.setTimeout(() => ctl.abort(), 5000);
    style = fetch(`/api/basemap/style/${theme}`, { signal: ctl.signal })
      .then((r) => (r.ok ? (r.json() as Promise<StyleSpecification>) : null))
      .catch(() => null)
      .finally(() => window.clearTimeout(timer));
    style.then((st) => { if (!st) baseStyles.delete(theme); });
    baseStyles.set(theme, style);
  }
  return style;
}

function outlineBase(): StyleSpecification {
  return {
    version: 8,
    sources: { world: { type: "geojson", data: "/world.json", attribution: "Outlines: Natural Earth" } },
    layers: [
      { id: "sea", type: "background", paint: { "background-color": cssVar("--sea") } },
      { id: "land", type: "fill", source: "world", paint: { "fill-color": cssVar("--land") } },
      { id: "borders", type: "line", source: "world", paint: { "line-color": cssVar("--text-secondary"), "line-width": 0.5, "line-opacity": 0.6 } },
    ],
  };
}

const OVERLAY = ["region", "cells", "area", "draft", "points"];
// roads, buildings, borders and names stay readable on top of the trend colours
const ON_TOP = new Set(["transportation", "transportation_name", "building", "boundary", "aeroway"]);

/** Trend colours fade as you zoom in, so streets and names show through. */
function cellOpacity(strength: number): maplibregl.DataDrivenPropertyValueSpecification<number> {
  const at = (zoom: number, k: number) => [zoom, ["*", strength * k, ["get", "opacity"]]];
  return ["interpolate", ["linear"], ["zoom"], ...at(4, 1), ...at(10, 0.6), ...at(14, 0.35)] as maplibregl.DataDrivenPropertyValueSpecification<number>;
}

function compose(base: StyleSpecification | null, strength: number, globe: boolean): StyleSpecification {
  const b = base ?? outlineBase();
  const layers = [...b.layers];
  let at = layers.findIndex((l) => l.type === "symbol" || l.id === "borders" || ON_TOP.has((l as { "source-layer"?: string })["source-layer"] ?? ""));
  if (at < 0) at = layers.length;
  layers.splice(at, 0, {
    id: "cells", type: "fill", source: "cells",
    paint: { "fill-color": ["get", "color"], "fill-opacity": cellOpacity(strength), "fill-antialias": false },
  });
  const top: LayerSpecification[] = [
    { id: "area", type: "line", source: "area", paint: { "line-color": cssVar("--text-secondary"), "line-width": 1.5, "line-dasharray": [2, 2] } },
    { id: "region-line", type: "line", source: "region", paint: { "line-color": cssVar("--text-primary"), "line-width": 2 } },
    { id: "draft", type: "line", source: "draft", paint: { "line-color": cssVar("--series-2"), "line-width": 2 } },
    {
      id: "points", type: "circle", source: "points",
      paint: { "circle-radius": 5, "circle-color": cssVar("--series-2"), "circle-stroke-color": cssVar("--surface-1"), "circle-stroke-width": 2 },
    },
  ];
  const sources = { ...b.sources };
  for (const id of OVERLAY) sources[id] = { type: "geojson", data: EMPTY };
  return { ...b, sources, layers: [...layers, ...top], projection: { type: globe ? "globe" : "mercator" } };
}

type Cursor = {
  lng: number; lat: number; zoom: number; tapped: boolean;
  cell?: { s: number; q: number | null; pass: boolean; color: string; la: number; lo: number; res: number };
  site?: string;
};
type T = (s: string, vars?: Record<string, string | number>) => string;

// 48.86° N, 2.35° E: more decimals as you zoom in (2 decimals ≈ 1 km, 4 ≈ 10 m)
function coords(lat: number, lng: number, zoom: number, t: T) {
  const d = zoom >= 12 ? 4 : zoom >= 7 ? 3 : 2;
  const lon = ((((lng + 180) % 360) + 360) % 360) - 180;
  return `${Math.abs(lat).toFixed(d)}° ${lat >= 0 ? t("N") : t("S")}, ${Math.abs(lon).toFixed(d)}° ${lon >= 0 ? t("E") : t("W")}`;
}

function readoutText(c: Cursor, units: string, t: T) {
  const parts = [coords(c.lat, c.lng, c.zoom, t)];
  if (c.cell) parts.push(`${fmtSigned(c.cell.s, 2)} ${t("{units} per decade", { units })}`, c.cell.pass ? t("passes the false-discovery test") : t("does not pass the false-discovery test"));
  if (c.site) parts.push(c.site);
  return parts.join(" · ");
}

const PIN = "M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21ZM12 7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z";

function Readout({ cursor: c, units: unitsRaw, hasCells, faded }: { cursor: Cursor; units: string; hasCells: boolean; faded: boolean }) {
  const { t, lang } = useI18n();
  const units = changeUnit(unitsRaw, lang);
  return (
    <div className="map-readout" aria-hidden="true">
      <div className="map-readout-pos">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d={PIN} /></svg>
        {coords(c.lat, c.lng, c.zoom, t)}
      </div>
      {c.cell ? (
        <div className="map-readout-cell">
          <span className="map-readout-swatch" style={{ background: c.cell.color, opacity: faded && !c.cell.pass ? 0.4 : 1 }} />
          <strong>{fmtSigned(c.cell.s, 2)} {t("{units} per decade", { units })}</strong>
          <span />
          <span className={c.cell.pass ? "ok-text" : "muted"}>
            {c.cell.pass ? t("passes the false-discovery test") : t("does not pass the false-discovery test")}
            {c.cell.q !== null && <> (q {c.cell.q < 0.001 ? "< 0.001" : `= ${fmt(c.cell.q, 2)}`})</>}
          </span>
          <span />
          <span className="muted">{t("cell of {res}° around {where}", { res: fmt(c.cell.res, 2), where: coords(c.cell.la, c.cell.lo, 0, t) })}</span>
        </div>
      ) : hasCells ? (
        <div className="map-readout-note muted">{t("No cell here: outside the region or no data.")}</div>
      ) : null}
      {c.site && <div className="map-readout-site">{t("Site")}: <strong>{c.site}</strong></div>}
    </div>
  );
}

export default function EarthMap({ outlines, cells, variable = "", units: unitsRaw = "", dataArea, drawMode, onBox, height, points, detailRequest }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [styleTick, setStyleTick] = useState(0); // counts style loads; sources are refilled after each
  const ready = styleTick > 0;
  const [globe, setGlobe] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [strength, setStrength] = useState(1);
  const [cursor, setCursor] = useState<Cursor | null>(null);
  const [themeTick, setThemeTick] = useState(0);
  const [detailed, setDetailed] = useState(false); // street map shown (not just the outlines)
  const drawStart = useRef<maplibregl.LngLat | null>(null);
  const live = useRef({ strength: 1, globe: false });
  live.current = { strength, globe };
  const { t, lang } = useI18n();
  const units = changeUnit(unitsRaw, lang); // the map shows rates: "pp" for a % quantity
  const tNow = useRef(t);
  tNow.current = t;

  // ---- create the map once (with the detailed base map when it can be had) ------------------
  useEffect(() => {
    let gone = false;
    let undo = () => {};
    const theme: Theme = isDark() ? "dark" : "light";
    loadBase(theme).then((base) => {
      if (gone || !box.current || map.current) return;
      const m = new maplibregl.Map({
        container: box.current,
        style: compose(base, live.current.strength, live.current.globe),
        center: [0, 20],
        zoom: 0,
        minZoom: -2,
        maxZoom: 19,
        attributionControl: false,
        renderWorldCopies: false,
        // the style names files as /api/basemap/...; the tile worker needs whole addresses
        transformRequest: (url) => ({ url: url.startsWith("/") ? window.location.origin + url : url }),
        locale: {
          "NavigationControl.ZoomIn": tNow.current("Zoom in"),
          "NavigationControl.ZoomOut": tNow.current("Zoom out"),
          "GeolocateControl.FindMyLocation": tNow.current("Show my location"),
        },
      });
      m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      m.addControl(
        new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: false, timeout: 10000 }, fitBoundsOptions: { maxZoom: 14 } }),
        "top-right",
      );
      m.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");
      m.addControl(new maplibregl.AttributionControl());
      m.getCanvas().setAttribute("aria-label", "Map. Drag or use the arrow keys to move, plus and minus to zoom.");
      m.on("style.load", () => {
        setDetailed(!m.getSource("world"));
        setStyleTick((x) => x + 1);
      });

      // if the street map's tiles cannot be had, go back to the outlines rather than a blank map
      let tilesOk = false;
      let failures = 0;
      m.on("data", (e) => {
        if (e.dataType === "source" && "tile" in e && e.tile && !OVERLAY.includes((e as { sourceId?: string }).sourceId ?? "")) tilesOk = true;
      });
      m.on("error", (e) => {
        const id = (e as { sourceId?: string }).sourceId;
        if (!id || OVERLAY.includes(id) || id === "world" || tilesOk) return;
        failures += 1;
        if (failures >= 3 || !(e as { tile?: unknown }).tile) { // 3 tiles, or the tile index itself
          detailedBroken = true;
          tilesOk = true; // switch once
          m.setStyle(compose(null, live.current.strength, live.current.globe), { diff: false });
        }
      });

      map.current = m;
      const onTheme = () => setThemeTick((x) => x + 1);
      window.addEventListener("mt-theme", onTheme);
      const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
      mq?.addEventListener?.("change", onTheme);
      undo = () => {
        window.removeEventListener("mt-theme", onTheme);
        mq?.removeEventListener?.("change", onTheme);
        m.remove();
        map.current = null;
      };
    });
    return () => { gone = true; undo(); };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    m.getCanvas().setAttribute("aria-label", t("Map. Drag or use the arrow keys to move, plus and minus to zoom."));
    const label = (sel: string, text: string) => {
      const b = box.current?.querySelector<HTMLButtonElement>(sel);
      if (b && !b.disabled) { b.title = text; b.setAttribute("aria-label", text); }
    };
    label(".maplibregl-ctrl-zoom-in", t("Zoom in"));
    label(".maplibregl-ctrl-zoom-out", t("Zoom out"));
    label(".maplibregl-ctrl-geolocate", t("Show my location"));
  }, [t, ready]);

  // ---- light or dark page: the matching base map, same view --------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !themeTick) return;
    let gone = false;
    loadBase(isDark() ? "dark" : "light").then((base) => {
      if (gone || map.current !== m) return;
      m.setStyle(compose(base, live.current.strength, live.current.globe), { diff: false });
    });
    return () => { gone = true; };
  }, [themeTick]);

  // ---- outlines and the data area ---------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    const region = m?.getSource("region") as GeoJSONSource | undefined;
    const area = m?.getSource("area") as GeoJSONSource | undefined;
    if (!region || !area) return;
    const feats: GeoJSON.Feature[] = outlines
      .map((o) => (o.geometry ? o.geometry : o.bbox ? bboxPolygon(o.bbox) : null))
      .filter(Boolean)
      .map((g) => ({ type: "Feature", properties: {}, geometry: g as GeoJSON.Geometry }));
    region.setData({ type: "FeatureCollection", features: feats });
    area.setData(dataArea ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: bboxPolygon(dataArea) }] } : EMPTY);
  }, [outlines, dataArea, styleTick]);

  // a new region moves the view (a new base map, colour change or re-render does not)
  const fitKey = JSON.stringify(outlines.map((o) => o.bbox ?? null));
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const bbs = (JSON.parse(fitKey) as (number[] | null)[]).filter(Boolean) as number[][];
    if (!bbs.length) return;
    let w = Math.min(...bbs.map((b) => b[0])), s = Math.min(...bbs.map((b) => b[1]));
    let e = Math.max(...bbs.map((b) => (b[2] < b[0] ? b[2] + 360 : b[2]))), n = Math.max(...bbs.map((b) => b[3]));
    if (e - w > 300) { w = -180; e = 180; }
    s = Math.max(s, -85); n = Math.min(n, 85);
    m.resize();
    m.fitBounds([[w, s], [e, n]], { padding: 30, duration: reducedMotion() ? 0 : 600, maxZoom: 10 });
  }, [fitKey, ready]);

  // ---- points (GLOBE sites) ----------------------------------------------------------------
  useEffect(() => {
    const src = map.current?.getSource("points") as GeoJSONSource | undefined;
    if (!src) return;
    src.setData({
      type: "FeatureCollection",
      features: (points ?? []).map((pt) => ({ type: "Feature", properties: { name: pt.name }, geometry: { type: "Point", coordinates: [pt.lon, pt.lat] } })),
    });
  }, [points, styleTick]);

  // ---- cells -------------------------------------------------------------------------------
  const ramp = useCallback(() => divergingFor(variable, isDark()), [variable]);
  const scaleMax = cells && !("skipped" in cells)
    ? (() => {
        const v = cells.slope_per_decade.filter((x): x is number => x !== null).map(Math.abs).sort((a, b) => a - b);
        return v.length ? v[Math.min(v.length - 1, Math.floor(v.length * 0.98))] || v[v.length - 1] || 1 : 1;
      })()
    : 1;

  // ---- big regions: merged blocks for the whole region, full detail for the area in view --------
  const merged = !!cells && !("skipped" in cells) && (cells.block ?? 1) > 1;
  const [detail, setDetail] = useState<CellMap | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const detailCache = useRef(new Map<string, CellMap>());
  useEffect(() => { setDetail(null); detailCache.current.clear(); }, [cells]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !merged || !detailRequest) return;
    const regionBox = (JSON.parse(fitKey) as (number[] | null)[]).find(Boolean) ?? [-180, -90, 180, 90];
    const rw = regionBox[2] > regionBox[0] ? regionBox[2] - regionBox[0] : regionBox[2] + 360 - regionBox[0];
    const rh = regionBox[3] - regionBox[1];
    let timer = 0;
    let ctl: AbortController | null = null;
    const update = () => {
      const b = m.getBounds();
      const w = Math.max(-180, b.getWest()), e = Math.min(180, b.getEast());
      const s = Math.max(-90, b.getSouth()), n = Math.min(90, b.getNorth());
      // zoomed out to most of the region: the merged map is the right one
      if ((e - w) * (n - s) > 0.5 * rw * rh || e <= w) { ctl?.abort(); setDetail(null); setDetailBusy(false); return; }
      // snap the box outwards, so small moves reuse the same result
      const step = Math.min(30, Math.max(0.5, 2 ** Math.round(Math.log2(Math.max(e - w, n - s) / 4))));
      const view = [
        Math.max(-180, Math.floor(w / step) * step), Math.max(-90, Math.floor(s / step) * step),
        Math.min(180, Math.ceil(e / step) * step), Math.min(90, Math.ceil(n / step) * step),
      ];
      const key = view.join(",");
      const hit = detailCache.current.get(key);
      if (hit) { setDetail(hit); return; }
      ctl?.abort();
      ctl = new AbortController();
      setDetailBusy(true);
      apiPost<CellMap>("/analysis/cells", { ...detailRequest, view }, ctl.signal, false)
        .then((r) => {
          detailCache.current.set(key, r);
          setDetail("skipped" in r ? null : r);
          setDetailBusy(false);
        })
        .catch((err: Error) => { if (err.name !== "AbortError") setDetailBusy(false); });
    };
    const onMove = () => { window.clearTimeout(timer); timer = window.setTimeout(update, 450); };
    m.on("moveend", onMove);
    return () => { m.off("moveend", onMove); window.clearTimeout(timer); ctl?.abort(); };
  }, [ready, merged, detailRequest, fitKey]);

  const shown = detail ?? cells; // what the map draws; the colour scale stays the region's

  useEffect(() => {
    const src = map.current?.getSource("cells") as GeoJSONSource | undefined;
    if (!src) return;
    const cells = shown;
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
        properties: { color, opacity: showRaw || cells.passes[i] ? 0.85 : 0.22, s, q: cells.q[i], pass: cells.passes[i], la, lo, res: cells.res },
        geometry: { type: "Polygon", coordinates: [[[lo - h, la - h], [lo + h, la - h], [lo + h, la + h], [lo - h, la + h], [lo - h, la - h]]] },
      });
    }
    src.setData({ type: "FeatureCollection", features: feats });
  }, [shown, styleTick, showRaw, ramp, scaleMax]);

  useEffect(() => {
    const m = map.current;
    if (m?.getLayer("cells")) m.setPaintProperty("cells", "fill-opacity", cellOpacity(strength));
  }, [strength, styleTick]);

  // ---- what is under the pointer (or under a tap on touch screens) ----------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let raf = 0;
    const read = (e: maplibregl.MapMouseEvent, tapped: boolean) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const layers = ["cells", "points"].filter((id) => m.getLayer(id));
        const hits = layers.length ? m.queryRenderedFeatures(e.point, { layers }) : [];
        const c = hits.find((f) => f.layer.id === "cells")?.properties;
        const site = hits.find((f) => f.layer.id === "points")?.properties?.name;
        setCursor({
          lng: e.lngLat.lng, lat: e.lngLat.lat, zoom: m.getZoom(), tapped,
          cell: c ? { s: Number(c.s), q: c.q == null ? null : Number(c.q), pass: String(c.pass) === "true", color: String(c.color), la: Number(c.la), lo: Number(c.lo), res: Number(c.res) } : undefined,
          site: site ? String(site) : undefined,
        });
        m.getCanvas().style.cursor = c || site ? "crosshair" : "";
      });
    };
    let touched = 0; // after a tap the browser adds mouse events, ending with a "mouseout": keep the readout
    const touch = () => { touched = Date.now(); };
    const move = (e: maplibregl.MapMouseEvent) => read(e, false);
    const tap = (e: maplibregl.MapMouseEvent) => read(e, true);
    const out = () => {
      if (Date.now() - touched < 1500) return;
      cancelAnimationFrame(raf); setCursor(null); m.getCanvas().style.cursor = "";
    };
    const drag = () => setCursor((cur) => (cur?.tapped ? null : cur)); // a tapped readout goes when the map moves
    m.on("touchstart", touch);
    m.on("mousemove", move);
    m.on("click", tap);
    m.on("mouseout", out);
    m.on("dragstart", drag);
    return () => { cancelAnimationFrame(raf); m.off("touchstart", touch); m.off("mousemove", move); m.off("click", tap); m.off("mouseout", out); m.off("dragstart", drag); };
  }, [ready]);

  // ---- draw a box ---------------------------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (!drawMode) {
      m.dragPan.enable();
      (m.getSource("draft") as GeoJSONSource | undefined)?.setData(EMPTY);
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
      (m.getSource("draft") as GeoJSONSource | undefined)?.setData({ type: "Feature", properties: {}, geometry: bboxPolygon(toBox(drawStart.current, e.lngLat)) });
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
          <label className="row small map-range">
            {t("Colour strength")}
            <input
              type="range" min={0.2} max={1} step={0.1} value={strength}
              aria-valuetext={`${Math.round(strength * 100)}%`}
              onChange={(e) => setStrength(Number(e.target.value))}
            />
          </label>
        )}
        {hasCells && (
          <label className="row small">
            <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
            {t("Show raw view (no false-discovery fading)")}
          </label>
        )}
      </div>
      <div className="map-frame">
        <div ref={box} className="map-box" style={height ? { height } : undefined} />
        {cursor && <Readout cursor={cursor} units={units} hasCells={!!hasCells} faded={!showRaw} />}
      </div>
      <p className="visually-hidden" aria-live="polite">{cursor?.tapped ? readoutText(cursor, units, t) : ""}</p>
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
          {merged && (
            <p className="small map-detail" aria-live="polite" style={{ margin: 0 }}>
              {detailBusy
                ? t("Loading full detail for the area in view…")
                : detail && !("skipped" in detail)
                  ? t("Full detail for the area in view: {n} cells of {res}°. Zoom out to see the whole region again.", { n: detail.n_cells, res: detail.res })
                  : t("To fit the whole region, cells are merged into {res}° blocks (the data is {native}°). Zoom in on the map for full detail.", {
                      res: (cells as Exclude<CellMap, { skipped: string }>).res,
                      native: (cells as Exclude<CellMap, { skipped: string }>).native_res ?? "",
                    })}
            </p>
          )}
          <p className="small muted" style={{ margin: 0 }}>
            {t("{n} of {m} cells pass the false-discovery test (faded cells do not; q ≤ {q}, tuned for neighbouring cells that move together, Wilks 2016).", {
              n: (shown as Exclude<CellMap, { skipped: string }>).n_pass,
              m: (shown as Exclude<CellMap, { skipped: string }>).n_cells,
              q: (shown as Exclude<CellMap, { skipped: string }>).alpha_fdr,
            })}{" "}
            {t((shown as Exclude<CellMap, { skipped: string }>).caveat)} {t("Based on {basis}.", { basis: (shown as Exclude<CellMap, { skipped: string }>).basis })}
          </p>
        </div>
      )}
      {cells && "skipped" in cells && <p className="small muted">{t("Cell map:")} {cells.skipped}.</p>}
      {dataArea && <p className="small muted" style={{ margin: "4px 0 0" }}>{t("Dashed box: the only area this variable has data for so far.")}</p>}
      {detailed && <p className="small muted map-hint">{t("Zoom in to see streets, places and buildings, or use the location button to go to where you are.")}</p>}
    </div>
  );
}
