import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "MegavirTrace — is this place really changing?",
  description:
    "Honest, checkable answers to 'is this place really changing?' from NASA data: what is changing, where, how much, and whether it is significant.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applies the saved theme before paint (no flash).  Static string, no user input.
const themeScript = `try{var t=localStorage.getItem("mt-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Script id="mt-theme" strategy="beforeInteractive">
          {themeScript}
        </Script>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <Nav />
        <main id="main">{children}</main>
        <footer className="site-footer">
          <p>
            MegavirTrace · NASA Space Apps Challenge 2026, &ldquo;Be An Earth System Trend Detective!&rdquo; · Team Space Pirates
            Paradigm · Data: NASA (MODIS, OMI, AIRS, GPM IMERG, MERRA-2, GLDAS, GRACE/GRACE-FO, NASA-SSH, MiCASA, GISTEMP) ·
            Open source, Apache 2.0. A trend is not a cause.
          </p>
        </footer>
      </body>
    </html>
  );
}
