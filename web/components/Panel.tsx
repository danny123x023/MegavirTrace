"use client";

import { type CSSProperties, createContext, type ReactNode, type RefObject, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";

// A card that can fill the screen.  It uses the browser's full-screen mode (Esc leaves it); where
// that is not available for page elements (iPhone Safari), the card covers the window instead.
// Charts and maps inside read `usePanel().full` or CSS (.panel.is-full) to grow into the space.

type PanelState = { full: boolean; toggle: () => void; claimInline: () => () => void };
const PanelContext = createContext<PanelState | null>(null);

export const usePanel = () => useContext(PanelContext);

type Props = {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  as?: "section" | "article" | "div";
  "aria-label"?: string;
  "aria-labelledby"?: string;
};

export default function Panel({ children, className = "", style, as = "section", ...aria }: Props) {
  const ref = useRef<HTMLElement>(null);
  const [native, setNative] = useState(false);
  const [covering, setCovering] = useState(false);
  const [inlineButtons, setInlineButtons] = useState(0);
  const full = native || covering;

  useEffect(() => {
    const onChange = () => setNative(document.fullscreenElement === ref.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(() => {
    if (!covering) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setCovering(false); };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("panel-covering");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("panel-covering");
    };
  }, [covering]);

  // maps and charts measure their boxes on resize
  useEffect(() => {
    const a = requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    const b = window.setTimeout(() => window.dispatchEvent(new Event("resize")), 250);
    return () => { cancelAnimationFrame(a); window.clearTimeout(b); };
  }, [full]);

  const toggle = useCallback(async () => {
    const el = ref.current;
    if (!el) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => undefined);
      return;
    }
    if (covering) {
      setCovering(false);
      return;
    }
    if (document.fullscreenEnabled && el.requestFullscreen) {
      try {
        await el.requestFullscreen();
        return;
      } catch {
        /* not allowed here: cover the window instead */
      }
    }
    setCovering(true);
  }, [covering]);

  const claimInline = useCallback(() => {
    setInlineButtons((n) => n + 1);
    return () => setInlineButtons((n) => n - 1);
  }, []);

  const Tag = as as "section";
  return (
    <Tag
      ref={ref as RefObject<HTMLElement>}
      className={`card panel${full ? " is-full" : ""}${covering ? " is-covering" : ""}${className ? " " + className : ""}`}
      style={style}
      {...aria}
    >
      <PanelContext.Provider value={{ full, toggle, claimInline }}>
        {children}
        {inlineButtons === 0 && <FullscreenButton corner />}
      </PanelContext.Provider>
    </Tag>
  );
}

const EXPAND = "M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7";
const COLLAPSE = "M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7";

/** The full-screen switch of the enclosing Panel.  Put it in a header row (charts do); otherwise
 *  the Panel shows one in its top-right corner.  Renders nothing outside a Panel. */
export function FullscreenButton({ corner = false }: { corner?: boolean }) {
  const panel = usePanel();
  const { t } = useI18n();
  const claim = panel?.claimInline;
  useLayoutEffect(() => (corner || !claim ? undefined : claim()), [corner, claim]);
  if (!panel) return null;
  const label = panel.full ? t("Exit full screen") : t("Show full screen");
  return (
    <button type="button" className={`btn-icon panel-fs${corner ? " corner" : ""}`} aria-label={label} title={label} onClick={panel.toggle}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={panel.full ? COLLAPSE : EXPAND} />
      </svg>
    </button>
  );
}

/** Height for a chart: its usual height, or most of the screen while its Panel is full screen. */
export function useFullHeight(base: number, reserve = 230): number {
  const panel = usePanel();
  const [vh, setVh] = useState(0);
  useEffect(() => {
    if (!panel?.full) return;
    const f = () => setVh(window.innerHeight);
    f();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, [panel?.full]);
  return panel?.full && vh ? Math.max(base, vh - reserve) : base;
}
