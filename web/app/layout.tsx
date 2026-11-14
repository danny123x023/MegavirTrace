import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import Nav from "@/components/Nav";
import OfflineSupport from "@/components/OfflineSupport";
import SiteFooter, { SkipLink } from "@/components/SiteFooter";
import { LangProvider } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "MegavirTrace — is this place really changing?",
  description:
    "Honest, checkable answers to 'is this place really changing?' from NASA data: what is changing, where, how much, and whether it is significant.",
};

// Self-hosted at build time by next/font: no request to Google from visitors, works offline.
const inter = Inter({ subsets: ["latin", "latin-ext"], display: "swap", variable: "--font-inter" });

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applies the saved theme and layout before paint (no flash).  Static string, no user input.
const themeScript = `try{var d=document.documentElement,t=localStorage.getItem("mt-theme");if(t==="light"||t==="dark")d.dataset.theme=t;if(localStorage.getItem("mt-layout")==="centered")d.dataset.layout="centered"}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body>
        <Script id="mt-theme" strategy="beforeInteractive">
          {themeScript}
        </Script>
        <LangProvider>
          <SkipLink />
          <OfflineSupport />
          <Nav />
          <main id="main">{children}</main>
          <SiteFooter />
        </LangProvider>
      </body>
    </html>
  );
}
