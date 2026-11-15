import type { Metadata } from "next";
import { Suspense } from "react";
import ExploreClient from "./ExploreClient";

export const metadata: Metadata = { title: "Explore — MegavirTrace" };

export default function Page() {
  return (
    <Suspense fallback={<p className="spinner-note">Loading…</p>}>
      <ExploreClient />
    </Suspense>
  );
}
