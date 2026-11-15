"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n";

export function SkipLink() {
  const { t } = useI18n();
  return (
    <a className="skip-link" href="#main">
      {t("Skip to content")}
    </a>
  );
}

export default function SiteFooter() {
  const { lang, t } = useI18n();
  return (
    <footer className="site-footer">
      <p>
        MegavirTrace · NASA Space Apps Challenge 2026, &ldquo;Be An Earth System Trend Detective!&rdquo; · Team Space Pirates Paradigm ·{" "}
        {lang === "es" ? "Datos" : "Data"}: NASA (MODIS, OMI, AIRS, GPM IMERG, MERRA-2, GLDAS, GRACE/GRACE-FO, NASA-SSH, MiCASA, GISTEMP, CERES,
        NSIDC, OCO-2, GLOBE) · {lang === "es" ? "Código abierto, Apache 2.0." : "Open source, Apache 2.0."} {t("A trend is not a cause.")} · <Link href="/admin">{t("Admin panel")}</Link>
      </p>
    </footer>
  );
}
