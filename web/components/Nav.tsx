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

export default function Nav() {
  const path = usePathname();
  const { lang, setLang, t } = useI18n();
  const [theme, setTheme] = useState<"system" | "light" | "dark">("system");

  useEffect(() => {
    const t = document.documentElement.dataset.theme;
    if (t === "light" || t === "dark") setTheme(t);
  }, []);

  function cycle() {
    const next = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";
    setTheme(next);
    if (next === "system") {
      delete document.documentElement.dataset.theme;
      localStorage.removeItem("mt-theme");
    } else {
      document.documentElement.dataset.theme = next;
      localStorage.setItem("mt-theme", next);
    }
    window.dispatchEvent(new Event("mt-theme"));
  }

  if (path?.startsWith("/embed")) return null;
  return (
    <header className="site-header">
      <Link href="/" className="brand">
        <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M4 15 L9 11 L13 13 L20 7" fill="none" stroke="var(--series-2)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        MegavirTrace <small>{t("Earth trend detective")}</small>
      </Link>
      <nav className="site-nav" aria-label="Main">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} aria-current={path === l.href ? "page" : undefined}>
            {t(l.label)}
          </Link>
        ))}
      </nav>
      <span className="header-spacer" />
      <select aria-label={t("Language")} value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
        {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
      </select>
      <button type="button" onClick={cycle} title={t("Change colour theme (auto, dark, light)")}>
        {t(`Theme: ${theme === "dark" ? "dark" : theme === "light" ? "light" : "auto"}`)}
      </button>
    </header>
  );
}
