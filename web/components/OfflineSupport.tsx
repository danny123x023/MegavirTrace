"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";

// Registers the service worker (production builds) and shows when results come from this device.
export default function OfflineSupport() {
  const { t } = useI18n();
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      if (process.env.NODE_ENV === "production") {
        navigator.serviceWorker.register("/sw.js").catch(() => {});
      } else {
        // A worker left by a production build on the same address would keep serving its cached
        // copies of /_next/static files to the dev server, giving stale code and hydration errors.
        navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())).catch(() => {});
      }
    }
    const update = () => setOffline(!navigator.onLine);
    const fromDevice = () => setOffline(true);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    window.addEventListener("mt-offline-result", fromDevice);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
      window.removeEventListener("mt-offline-result", fromDevice);
    };
  }, []);
  if (!offline) return null;
  return (
    <div className="offline-banner" role="status">
      <span aria-hidden="true">⚡</span>
      {t("You are offline: showing results saved on this device.")}
    </div>
  );
}
