"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { type Lang, LANGS, useI18n } from "@/lib/i18n";

const LINKS = [
  { href: "/explore", label: "Explore" },
  { href: "/compare", label: "Compare" },
  { href: "/related", label: "Related variables" },
  { href: "/start", label: "Start here" },
  { href: "/cases", label: "Detective cases" },
  { href: "/ask", label: "Ask the AI" },
  { href: "/methods", label: "Method" },
  { href: "/imports", label: "Data import" },
];

const ICON = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

const TranslateIcon = () => (
  <svg {...ICON}>
    <path d="M4 5h8M8 3v2M10.5 5c-.6 3.6-3 6.6-6.5 8.5M6.5 9c1.4 2 3.3 3.5 5.5 4.5" />
    <path d="M13 21l4-9 4 9M14.4 18h5.2" />
  </svg>
);
const MoonIcon = () => (
  <svg {...ICON}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
  </svg>
);
const ExpandIcon = () => (
  <svg {...ICON}>
    <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
  </svg>
);

export default function Nav() {
  const path = usePathname();
  const { lang, setLang, t } = useI18n();
  const [dark, setDark] = useState(false);
  const [wide, setWide] = useState(true);

  useEffect(() => {
    const d = document.documentElement;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    // with no saved choice the device decides, so the button follows the device until it is used
    const sync = () => setDark(d.dataset.theme === "dark" || (d.dataset.theme !== "light" && mq.matches));
    sync();
    setWide(d.dataset.layout !== "centered");
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  function toggleDark() {
    const next = dark ? "light" : "dark";
    setDark(!dark);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("mt-theme", next);
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
      <div className="header-tools">
        <span className="select-icon">
          <TranslateIcon />
          <select aria-label={t("Language")} value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
            {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
        </span>
        <button type="button" className="tool-btn" aria-label={t("Dark mode")} aria-pressed={dark} onClick={toggleDark}>
          <MoonIcon />
          <span className="tool-label">{t("Dark mode")}</span>
          <span className="tool-label-short">{t("Dark")}</span>
        </button>
        <button type="button" className="tool-btn layout-toggle" aria-label={t("Full screen")} aria-pressed={wide} onClick={toggleLayout}>
          <ExpandIcon />
          <span className="tool-label">{t("Full screen")}</span>
        </button>
      </div>
    </header>
  );
}
