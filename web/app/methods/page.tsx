"use client";

import { useEffect, useState } from "react";
import { apiGet, type Catalog } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

type GiovanniCheck = { correlation: number; relative_mean_difference: number; months: number; points: number; period: string[]; giovanni_data: string; ok: boolean; mean_ours: number; mean_giovanni: number; units: string };

type Validation = {
  months?: number; valid_share?: number; area_mean?: number; is_global?: boolean;
  plausible?: { ok: boolean; range: number[]; note: string };
  nasa_official_check?: { correlation: number; mean_abs_difference: number; warming_since_1975_per_decade: { ours: number; nasa: number }; warmest_year: { ours: number; nasa: number }; ok: boolean };
};

export default function MethodsPage() {
  const { lang, t } = useI18n();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  useEffect(() => { apiGet<Catalog>("/variables").then(setCatalog).catch(() => {}); }, []);

  const gis = (catalog?.variables.find((v) => v.id === "temp_change")?.data?.validation as Validation | undefined)?.nasa_official_check;
  const giovanni = ["air_temp", "rainfall"]
    .map((id) => ({ id, name: catalog?.variables.find((v) => v.id === id)?.name, g: (catalog?.variables.find((v) => v.id === id)?.data?.validation as { giovanni_check?: GiovanniCheck } | undefined)?.giovanni_check }))
    .filter((x) => x.g);

  return (
    <div className="prose" style={{ maxWidth: "none" }}>
      <h1>{t("Method & data")}</h1>
      {lang !== "en" && <p className="small muted">{t("The detailed method below is in English.")}</p>}
      <p className="lede">
        Three commitments, never reduced: the four questions for any place on real NASA data; honest significance; and every number traceable.
      </p>

      <section className="card" aria-labelledby="m-h">
        <h2 id="m-h">{t("How a verdict is made")}</h2>
        <ol>
          <li><strong>Regional series.</strong> Area-weighted mean over the cells of the region (cell fraction × cos latitude × land or sea share), formed from each cell's departure from its usual value for that month so that a change in which cells have data is not mistaken for a trend, with the share of the region covered each month. A year needs 10 of 12 months (or the same share of the calendar months ever observed there, such as outside polar night); a season all 3. The monthly views show each month minus its usual value, and test the yearly means of those anomalies, because neighbouring months and the months of one El Niño year are not independent.</li>
          <li><strong>Least squares</strong> slope with a 95% interval and t-test; the standard error is widened with the effective sample size n<sub>eff</sub> = n(1 − r₁)/(1 + r₁), using the lag-1 autocorrelation of the residuals, corrected for its small-sample bias: about (2 + 5r₁)/n in long records (after van Giersbergen 2005), and measured by simulation for short ones.</li>
          <li><strong>Mann–Kendall</strong>, with the variance of S computed exactly for a Gaussian AR(1) series with that r₁ and referred to a t distribution with n<sub>eff</sub> − 2 degrees of freedom. This is an AR(1) correction, not the Hamed–Rao correction.</li>
          <li><strong>Sen&apos;s slope</strong> with its 95% interval is the headline rate, because it resists outliers; the interval uses the same t reference as the Mann–Kendall test.</li>
          <li><strong>Agreement rule.</strong> &ldquo;Significant&rdquo; needs both tests at α = 0.05 and all slopes pointing the same way. Monte Carlo tests in CI (2,000 AR(1) series per setting) hold false alarms to at most 5% at r₁ = 0.3 and at most 7% at r₁ = 0.5.</li>
          <li><strong>Years needed to detect</strong> a trend of this size (Weatherhead et al. 1998), so a non-significant result says how many more years are needed.</li>
          <li><strong>Size against the noise</strong> and a <strong>robustness</strong> check: Sen&apos;s slope must keep its sign in both halves, without the end years and leaving out any one year.</li>
          <li><strong>Where inside the region:</strong> the same agreement rule on every cell (tie-corrected Mann–Kendall and least squares, both corrected for memory; cells too persistent to test are left out), then Benjamini–Hochberg q-values with α<sub>FDR</sub> = 2α for spatially correlated fields (Wilks 2016). Cells that do not pass are faded.</li>
          <li><strong>Comparing two regions:</strong> the test runs on the trend of the difference series A − B (Santer et al. 2000), with the smallest difference the record could detect.</li>
          <li><strong>Plain words from fixed templates.</strong> The verdict is never written by AI. The optional AI scientist only explains stored results, and its numbers and directions are checked.</li>
        </ol>
        <p className="small">
          Every result has a fingerprint (request + data version + engine version) and a notebook download that recomputes every number with NumPy and SciPy alone.
          The open, read-only data API is documented at <a href="/api/docs">/api/docs</a>.
        </p>
      </section>

      <section className="card" style={{ marginTop: 16 }} aria-labelledby="v-h">
        <h2 id="v-h">{t("Checked against NASA's own numbers")}</h2>
        {gis ? (
          <p>
            <strong>GISTEMP:</strong> our global series from the gridded file matches NASA&apos;s official global series (GLB.Ts+dSST): correlation{" "}
            {fmt(gis.correlation, 4)}, mean difference {fmt(gis.mean_abs_difference, 2)} °C, warming since 1975 {fmt(gis.warming_since_1975_per_decade.ours, 3)} vs{" "}
            {fmt(gis.warming_since_1975_per_decade.nasa, 3)} °C per decade, warmest year {gis.warmest_year.ours} vs {gis.warmest_year.nasa}.{" "}
            {gis.ok ? "✓ Passed." : "✗ Did not pass."}
          </p>
        ) : (
          <p className="muted">The GISTEMP check runs after the import (megavir-ingest gistemp-check).</p>
        )}
        {giovanni.map(({ id, name, g }) => g && (
          <p key={id}>
            <strong>{name} vs NASA Giovanni</strong> ({g.giovanni_data}, test box, {g.points} points, {g.period[0]} to {g.period[1]}): correlation{" "}
            {fmt(g.correlation, 4)}, mean {fmt(g.mean_ours, 3)} vs {fmt(g.mean_giovanni, 3)} {g.units} (difference {fmt(g.relative_mean_difference * 100, 2)}%).{" "}
            {g.ok ? "✓ Passed (target: r ≥ 0.98, within 5%)." : "✗ Did not pass."}
          </p>
        ))}
        <p className="small muted">
          Regional IMERG and MERRA-2 series are checked against NASA Giovanni for the test box (target: correlation ≥ 0.98, mean difference within 5%), using
          Giovanni point time series on a grid across the box. Every product also gets a quick-look map and a global-mean plausibility check before it is used.
        </p>
      </section>

      <section className="card" style={{ marginTop: 16 }} aria-labelledby="d-h">
        <h2 id="d-h">{t("Data sources")}</h2>
        <div className="table-scroll" style={{ maxHeight: "none" }}>
          <table className="data">
            <thead>
              <tr><th scope="col">Variable</th><th scope="col" style={{ textAlign: "left" }}>Product</th><th scope="col" style={{ textAlign: "left" }}>DOI / reference</th><th scope="col">Loaded</th></tr>
            </thead>
            <tbody>
              {catalog?.variables.map((v) => {
                const doi = v.dataset_info.doi ?? v.dataset_info.paper_doi;
                return (
                  <tr key={v.id}>
                    <td>{v.name}<br /><span className="muted small">{v.theme} · {v.units}</span></td>
                    <td style={{ textAlign: "left" }}>{v.dataset_info.product}<br /><span className="muted small">{v.dataset_info.archive}</span></td>
                    <td style={{ textAlign: "left" }}>{doi ? <a href={`https://doi.org/${doi}`} rel="noopener noreferrer" target="_blank">{doi}</a> : "—"}</td>
                    <td>{v.data ? `${v.data.first_month} – ${v.data.last_month} (${v.data.kind})` : "not yet"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!!catalog?.planned.length && <h3 style={{ marginTop: 14 }}>Coming next</h3>}
        <ul>
          {catalog?.planned.map((p) => (
            <li key={p.id}>{p.name} — {p.dataset_info.product} (<a href={`https://doi.org/${p.dataset_info.doi}`} rel="noopener noreferrer" target="_blank">{p.dataset_info.doi}</a>)</li>
          ))}
        </ul>
        <p className="small muted">
          Ground observations: the NASA <a href="https://www.globe.gov" rel="noopener noreferrer" target="_blank">GLOBE Program</a> (schools and citizen scientists), through the GLOBE API; shown beside the series as context, never used in the tests.{" "}
          Climate projections: NASA NEX-GDDP-CMIP6 via NASA NCCS THREDDS (5 models, SSP2-4.5 and SSP5-8.5), shown as context.{" "}
          Place names: GeoNames (CC BY 4.0). Country and state outlines: Natural Earth (public domain). The design document and the methods paper draft are in the
          repository (docs/methods.md).
        </p>
      </section>

      <section className="card" style={{ marginTop: 16 }} aria-labelledby="r-h">
        <h2 id="r-h">{t("References")}</h2>
        <ul className="small">
          <li>Benjamini, Y. &amp; Hochberg, Y. (1995). Controlling the false discovery rate. <a href="https://doi.org/10.1111/j.2517-6161.1995.tb02031.x">doi:10.1111/j.2517-6161.1995.tb02031.x</a></li>
          <li>Hirsch, R. M., Slack, J. R. &amp; Smith, R. A. (1982). Techniques of trend analysis for monthly water quality data. <a href="https://doi.org/10.1029/WR018i001p00107">doi:10.1029/WR018i001p00107</a></li>
          <li>Lenssen, N. et al. (2019). Improvements in the GISTEMP uncertainty model. <a href="https://doi.org/10.1029/2018JD029522">doi:10.1029/2018JD029522</a></li>
          <li>Loomis, B. D., Luthcke, S. B. &amp; Sabaka, T. J. (2019). Regularization and error characterization of GRACE mascons. <a href="https://doi.org/10.1007/s00190-019-01252-y">doi:10.1007/s00190-019-01252-y</a></li>
          <li>Santer, B. D. et al. (2000). Statistical significance of trends and trend differences in layer-average atmospheric temperature time series. <a href="https://doi.org/10.1029/1999JD901105">doi:10.1029/1999JD901105</a></li>
          <li>Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall&apos;s tau. <a href="https://doi.org/10.1080/01621459.1968.10480934">doi:10.1080/01621459.1968.10480934</a></li>
          <li>van Giersbergen, N. P. A. (2005). On the effect of deterministic terms on the bias in stable AR models. <a href="https://doi.org/10.1016/j.econlet.2005.05.013">doi:10.1016/j.econlet.2005.05.013</a></li>
          <li>Weatherhead, E. C. et al. (1998). Factors affecting the detection of trends. <a href="https://doi.org/10.1029/98JD00995">doi:10.1029/98JD00995</a></li>
          <li>Wilks, D. S. (2016). &ldquo;The stippling shows statistically significant grid points&rdquo;. <a href="https://doi.org/10.1175/BAMS-D-15-00267.1">doi:10.1175/BAMS-D-15-00267.1</a></li>
        </ul>
      </section>
    </div>
  );
}
