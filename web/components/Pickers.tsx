"use client";

import { useEffect, useId, useRef, useState } from "react";
import { apiGet, type Catalog, type Place, type Region } from "@/lib/api";
import { THEME_ES, useI18n, varText } from "@/lib/i18n";

// ---- What -------------------------------------------------------------------------------------

export function VariablePicker({ catalog, value, onChange, label = "What" }: { catalog: Catalog | null; value: string; onChange: (v: string) => void; label?: string }) {
  const id = useId();
  const { lang, t } = useI18n();
  return (
    <div className="field">
      <label htmlFor={id}>{t(label)}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={!catalog}>
        {!catalog && <option>{t("Loading…")}</option>}
        {catalog?.themes.map((theme) => (
          <optgroup key={theme} label={lang === "es" ? THEME_ES[theme] ?? theme : theme}>
            {catalog.variables
              .filter((v) => v.theme === theme)
              .map((v) => (
                <option key={v.id} value={v.id} disabled={!v.data}>
                  {varText(v, lang)}
                  {!v.data ? ` ${t("(not loaded yet)")}` : v.data.kind !== "real" ? ` (${t(`${v.data.kind} data`)})` : ""}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

// ---- Where ------------------------------------------------------------------------------------

export type Chosen = { region: Region; label: string; place?: Place | null };

type Preset = { id: string; name: string; bbox: number[]; try: string[] };

export function PlacePicker({
  value,
  onChange,
  onDrawToggle,
  drawing,
  label = "Where",
}: {
  value: Chosen | null;
  onChange: (c: Chosen) => void;
  onDrawToggle?: () => void;
  drawing?: boolean;
  label?: string;
}) {
  const id = useId();
  const listId = useId();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [presets, setPresets] = useState<{ name: string; presets: Preset[] }[]>([]);
  const [showBox, setShowBox] = useState(false);
  const [boxText, setBoxText] = useState({ w: "", s: "", e: "", n: "" });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { t } = useI18n();

  useEffect(() => {
    apiGet<{ groups: { name: string; presets: Preset[] }[] }>("/places/presets").then((r) => setPresets(r.groups)).catch(() => {});
  }, []);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (q.trim().length < 2) { setResults([]); return; }
    const ctl = new AbortController();
    timer.current = setTimeout(() => {
      apiGet<{ results: Place[] }>("/places/search", { q, limit: 10 }, ctl.signal)
        .then((r) => { setResults(r.results); setActive(0); setOpen(true); })
        .catch(() => {});
    }, 180);
    return () => { ctl.abort(); };
  }, [q]);

  function choose(p: Place) {
    setOpen(false);
    setQ("");
    onChange({ region: { place: p.id }, label: p.kind === "city" ? `Around ${p.name}` : p.name, place: p });
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(results.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(results[active]); }
    else if (e.key === "Escape") setOpen(false);
  }

  function applyBox() {
    const b = [boxText.w, boxText.s, boxText.e, boxText.n].map(Number);
    if (b.some((x) => !Number.isFinite(x)) || b[1] >= b[3]) return;
    onChange({ region: { bbox: b }, label: `Box ${b.join(", ")}` });
    setShowBox(false);
  }

  const kindWord: Record<string, string> = { country: t("Country"), admin1: t("State / province"), city: t("City (1° box)"), preset: t("Preset") };

  return (
    <div className="field" style={{ gap: 6 }}>
      <label htmlFor={id}>{t(label)}</label>
      <div className="row">
        <div className="combo">
          <input
            id={id}
            type="search"
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
            placeholder={value ? value.label : t("Search a country, state or city…")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            autoComplete="off"
          />
          {open && results.length > 0 && (
            <ul id={listId} role="listbox" aria-label={t("Places")}>
              {results.map((r, i) => (
                <li
                  key={r.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => { e.preventDefault(); choose(r); }}
                >
                  {r.name} <small>· {kindWord[r.kind] ?? r.kind}{r.context ? ` · ${r.context}` : ""}</small>
                </li>
              ))}
            </ul>
          )}
        </div>
        <select
          aria-label={t("Or choose a preset region")}
          value=""
          onChange={(e) => {
            const p = presets.flatMap((g) => g.presets).find((x) => x.id === e.target.value);
            if (p) onChange({ region: { place: p.id }, label: p.name });
          }}
        >
          <option value="">{t("Presets…")}</option>
          {presets.map((g) => (
            <optgroup key={g.name} label={g.name}>
              {g.presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </optgroup>
          ))}
        </select>
        {onDrawToggle && (
          <button type="button" aria-pressed={!!drawing} onClick={onDrawToggle} title={t("Drag on the map to draw a box")}>
            {drawing ? t("Drawing… drag on the map") : t("Draw a box")}
          </button>
        )}
        <button type="button" onClick={() => setShowBox((s) => !s)} aria-expanded={showBox}>{t("Type a box")}</button>
      </div>
      {showBox && (
        <div className="row small">
          {(["w", "s", "e", "n"] as const).map((k) => (
            <label key={k} className="row" style={{ gap: 4 }}>
              {t({ w: "West", s: "South", e: "East", n: "North" }[k])}
              <input type="number" step="0.5" style={{ width: 90 }} value={boxText[k]} onChange={(e) => setBoxText({ ...boxText, [k]: e.target.value })} />
            </label>
          ))}
          <button type="button" onClick={applyBox}>{t("Use box")}</button>
        </div>
      )}
      {value && <span className="small muted">{t("Chosen:")} <strong>{value.label}</strong></span>}
    </div>
  );
}

// ---- How ----------------------------------------------------------------------------------------

export type ModeState = { mode: string; season: string; start: string; end: string };

const ALL_MODES: [string, string][] = [
  ["annual", "Yearly"],
  ["season", "Season"],
  ["monthly", "Monthly anomalies"],
  ["raw", "Raw months"],
];

export function ModeControls({ value, onChange, withRaw = true }: { value: ModeState; onChange: (m: ModeState) => void; withRaw?: boolean }) {
  const { t } = useI18n();
  const modes = withRaw ? ALL_MODES : ALL_MODES.filter(([k]) => k !== "raw");
  return (
    <div className="field">
      <span className="label" id="mode-label">{t("How")}</span>
      <div className="row">
        <div className="segmented" role="group" aria-labelledby="mode-label">
          {modes.map(([k, l]) => (
            <button key={k} type="button" aria-pressed={value.mode === k} onClick={() => onChange({ ...value, mode: k })}>{t(l)}</button>
          ))}
        </div>
        {value.mode === "season" && (
          <select aria-label={t("Season")} value={value.season} onChange={(e) => onChange({ ...value, season: e.target.value })}>
            <option value="DJF">{t("Dec–Feb")}</option>
            <option value="MAM">{t("Mar–May")}</option>
            <option value="JJA">{t("Jun–Aug")}</option>
            <option value="SON">{t("Sep–Nov")}</option>
          </select>
        )}
        <label className="row small" style={{ gap: 4 }}>
          {t("From")}
          <input type="number" min={1850} max={2100} style={{ width: 84 }} value={value.start} placeholder={t("first")} onChange={(e) => onChange({ ...value, start: e.target.value })} />
        </label>
        <label className="row small" style={{ gap: 4 }}>
          {t("to")}
          <input type="number" min={1850} max={2100} style={{ width: 84 }} value={value.end} placeholder={t("last")} onChange={(e) => onChange({ ...value, end: e.target.value })} />
        </label>
      </div>
    </div>
  );
}
