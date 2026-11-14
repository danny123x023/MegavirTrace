"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";

// Registers the service worker (production builds) and shows when results come from this device.
export default function OfflineSupport() {
  const { t } = useI18n();
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
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
