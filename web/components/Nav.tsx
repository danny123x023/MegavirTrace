"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { type Lang, LANGS, useI18n } from "@/lib/i18n";

const LINKS = [
  { href: "/", label: "Explore" },
  { href: "/compare", label: "Compare" },
  { href: "/related", label: "Moves together" },
  { href: "/start", label: "Start here" },
  { href: "/ask", label: "Ask the AI" },
  { href: "/methods", label: "Method" },
];

type Theme = "system" | "light" | "dark";

const ICON = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

function ThemeIcon({ mode }: { mode: Theme }) {
  if (mode === "light")
    return (
      <svg {...ICON}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    );
  if (mode === "dark")
    return (
      <svg {...ICON}>
        <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
      </svg>
    );
  return (
    <svg {...ICON}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

function LayoutIcon({ wide }: { wide: boolean }) {
  // arrows pointing in when the page is full width (click to centre), out when it is centred
  return wide ? (
    <svg {...ICON}>
      <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" />
    </svg>
  ) : (
    <svg {...ICON}>
      <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
    </svg>
  );
}

const THEMES: { id: Theme; label: string }[] = [
  { id: "system", label: "Auto (follow the device)" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

export default function Nav() {
  const path = usePathname();
  const { lang, setLang, t } = useI18n();
  const [theme, setTheme] = useState<Theme>("system");
  const [wide, setWide] = useState(true);

  useEffect(() => {
    const d = document.documentElement;
    if (d.dataset.theme === "light" || d.dataset.theme === "dark") setTheme(d.dataset.theme);
    setWide(d.dataset.layout !== "centered");
  }, []);

  function applyTheme(next: Theme) {
    setTheme(next);
    const d = document.documentElement;
    try {
      if (next === "system") {
        delete d.dataset.theme;
        localStorage.removeItem("mt-theme");
      } else {
        d.dataset.theme = next;
        localStorage.setItem("mt-theme", next);
      }
    } catch {
      /* private mode: the choice lasts for this page only */
    }
    window.dispatchEvent(new Event("mt-theme"));
  }

  function toggleLayout() {
    const next = !wide;
    setWide(next);
    const d = document.documentElement;
    try {
      if (next) {
        delete d.dataset.layout;
        localStorage.removeItem("mt-layout");
      } else {
        d.dataset.layout = "centered";
        localStorage.setItem("mt-layout", "centered");
      }
    } catch {
      /* private mode */
    }
    // the map and charts re-measure their boxes
    window.dispatchEvent(new Event("resize"));
  }

  if (path?.startsWith("/embed")) return null;
  return (
    <header className="site-header">
      <Link href="/" className="brand">
        <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M4 15 L9 11 L13 13 L20 7" fill="none" stroke="var(--series-2)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="brand-name">MegavirTrace</span>
        <span className="brand-tag">{t("Earth system trend detective")}</span>
      </Link>
      <nav className="site-nav" aria-label="Main">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} aria-current={path === l.href ? "page" : undefined}>
            {t(l.label)}
          </Link>
        ))}
      </nav>
      <span className="header-spacer" />
      <div className="header-tools">
        <select className="compact" aria-label={t("Language")} value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
          {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
        </select>
        <div className="segmented icons" role="group" aria-label={t("Colour theme")}>
          {THEMES.map((m) => (
            <button key={m.id} type="button" aria-pressed={theme === m.id} aria-label={t(m.label)} title={t(m.label)} onClick={() => applyTheme(m.id)}>
              <ThemeIcon mode={m.id} />
            </button>
          ))}
        </div>
        <button
          type="button"
          className="icon-btn layout-toggle"
          aria-pressed={wide}
          aria-label={t("Full width")}
          title={t(wide ? "Switch to a centred layout" : "Switch to full width")}
          onClick={toggleLayout}
        >
          <LayoutIcon wide={wide} />
        </button>
      </div>
    </header>
  );
}
