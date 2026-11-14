import { Suspense } from "react";
import ExploreClient from "./ExploreClient";

export default function Page() {
  return (
    <Suspense fallback={<p className="spinner-note">Loading…</p>}>
      <ExploreClient />
    </Suspense>
  );
}
