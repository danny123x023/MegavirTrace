# MegavirTrace: honest regional trend detection from NASA Earth-observation records

*Methods paper, draft.* Team Space Pirates Paradigm, NASA Space Apps Challenge 2026.

## Abstract

MegavirTrace answers four questions for any region on Earth, for 16 NASA variables: what is changing, where,
how much, and whether the change is significant. It is built around three commitments. Significance is
claimed only when two independent tests agree after correction for serial correlation, and false alarms are
measured by Monte Carlo rather than assumed. Every number comes from one deterministic engine and can be
recomputed from an exported notebook. The verdict is written from fixed templates, never by a language model.
Against NASA's official GISTEMP global series, our pipeline reproduces the annual means with r = 0.9997 and
the 1975–present warming rate within 0.002 °C per decade.

## 1. Data

Eleven NASA products feed one monthly store (Table 1 of the design document). The products are OMI OMNO2d
v004, GLDAS Noah 2.1, GPM IMERG V07, MiCASA v1, MODIS MOD13C2 v061, NASA-SSH v1, MERRA-2 M2SMNXSLV and
M2TMNXSLV, the GSFC GRACE/GRACE-FO mascons, AIRS AIRS3STM v7 and GISTEMP v4.

Fields are regridded conservatively to a common 0.5° grid. AIRS keeps its 1° grid and GISTEMP its 2° grid.
For regular latitude–longitude cells the regridding separates into a latitude overlap matrix, weighted by
Δ(sin φ) (true area), and a longitude overlap matrix that wraps at the dateline for global grids. Missing data
are regridded as a valid-area mask: an output cell gets a value only when at least half its area had data,
and that value is the area-weighted mean of the valid part. This preserves the global mean (tested).

Units are converted to everyday ones: mm per month (from mm h⁻¹ or kg m⁻² s⁻¹), °C (from K), mm of sea level,
10¹⁵ molecules cm⁻² for NO₂, and g C m⁻² per month for fire emissions. Daily OMI data form a monthly mean when
a cell has at least 3 valid days; weekly NASA-SSH grids need at least 2 weeks.

## 2. Regional series

For a region R (a polygon or a box), each grid cell *i* gets the weight

w_i = f_i · cos φ_i · m_i,

where f_i is the fraction of the cell inside R (from exact polygon intersection) and m_i is the land or sea
fraction for land-only or sea-only variables. The monthly regional value is the weighted mean over valid
cells. The *coverage* is the share of the region's weight that had data. Months with coverage below 50% are
treated as missing, and the lowest coverage used is reported as a caveat.

Monthly values become:
- **yearly values:** a year needs at least 10 of 12 months, and its value is the 12-month climatological mean
  plus the mean anomaly of the months present, so a missing winter month does not bias the year;
- **seasonal values:** all 3 months are needed, and December belongs to the following DJF;
- **monthly anomalies:** each month minus its calendar month's mean over the chosen years, tested with the
  seasonal Mann–Kendall test.

## 3. Trend tests

Let *n* be the number of values and r̂₁ the lag-1 autocorrelation of the least-squares residuals, computed
using only neighbours exactly one step apart. Residuals of a fitted line underestimate r₁ by about
(2 + 4r₁)/n (van Giersbergen 2005), so we use r₁ = (n r̂₁ + 2)/(n − 4), clipped to [0, 0.95] for the
corrections.

**Least squares.** The slope's standard error is widened by √((n − 2)/(n_eff − 2)), with
n_eff = n(1 − r₁)/(1 + r₁) (Santer et al. 2000). The test is a t-test with n_eff − 2 degrees of freedom.

**Mann–Kendall.** The variance of S under a Gaussian AR(1) process is computed exactly from the pairwise sign
covariances E[sgn D_p sgn D_q] = (2/π) arcsin ρ(D_p, D_q), summed over all pairs of pairs. With regular
sampling the sum collapses to O(n³) classes of (u, v, w) offsets with closed-form multiplicities, and seasons
are handled by an offset in months. This reduces to n(n − 1)(2n + 5)/18 when r₁ = 0 and matches simulation
within Monte Carlo error. We tabulate the ratio Var_AR1/Var_iid on a grid of n and r₁ and interpolate
linearly in r₁ and 1/n. The tie-corrected variance is multiplied by this ratio. This is an AR(1) model
correction, not the Hamed–Rao (1998) empirical correction.

Because r₁ is itself estimated, a normal reference for Z is too eager: about 8% false alarms at r₁ = 0.5 and
n = 20, whereas an oracle that knows r₁ gives 4–5%. We therefore refer Z to a t distribution with the same
n_eff − 2 degrees of freedom as the least-squares test.

**Sen's slope** is the headline rate, with Gilbert's (1987) interval computed from the corrected Var(S).

**Agreement rule.** "Significant" requires p < 0.05 in both tests, and the least-squares slope, Sen's slope
and S must have the same sign.

**Detectability.** Following Weatherhead et al. (1998), a trend ω needs about
n* = [3.3 σ_N √(12/k) / |ω| · √((1 + φ)/(1 − φ))]^{2/3} years to be detected, where k is the number of values
per year. Weatherhead's formula is written for monthly data; with yearly values the slope variance scales by
12. A non-significant verdict reports how many more years the record would need.

**Size against the noise and robustness.** We report the change of the trend line over the record divided by
the residual scatter (small < 0.5 ≤ moderate < 1 ≤ large < 2 ≤ very large). The trend is labelled *fragile*
if Sen's slope changes sign in either half of the record, without the first and last years, or with any one
year left out.

**Is it speeding up?** A straight line misreads acceleration, so the curvature term c of
y = a + b t + c t² is tested with the same autocorrelation treatment as the trend. We estimate r₁ from the
quadratic residuals, correct it for the bias of a three-parameter fit ((n r̂₁ + 3)/(n − 5)), widen the
standard error with n_eff, and use a t-test with n_eff − 3 degrees of freedom. A claim of "speeding up",
"slowing down" or "changed direction" needs p < 0.025 (stricter than for the trend itself), and the robust
Sen slopes of the two halves of the record must show the same change. At α = 0.05 a straight trend with
AR(1) noise was called accelerating 5–7% of the time at r₁ = 0.3. At 0.025 the rate is at most 3.3% at
r₁ = 0.3 and 4.8% at r₁ = 0.5, within the same targets as the trend test. The check needs at least 15 years.

**Exploratory clues.** These are labelled as such: years more than 2 SD from the trend line, and a continuous
two-piece (hinge) fit that is reported only when it beats the straight line by ΔBIC > 2.

## 4. Where inside the region

The same tests run, vectorised, on every cell's yearly (or seasonal) series. For speed, the Sen median uses
partitioning for complete cells and sorting for cells with gaps. Benjamini–Hochberg q-values are computed
across the region's cells, and a cell passes when q ≤ 2α. Wilks (2016) shows that controlling the FDR at
α_FDR = 2α keeps the field-wide false-alarm rate near α for spatially correlated fields. Because which cells
pass depends on the region tested, the map says so.

## 5. Comparing two regions

The test runs on the trend of the year-by-year difference A − B (Santer et al. 2000). Shared variability
cancels, so correlated regions are not under-tested and anti-correlated ones are not over-tested. We report
the difference per decade, its 95% interval, p, and the smallest difference the record could detect:
(t₀.₉₇₅ + t₀.₈₀) × SE_adj, for 80% power.

## 6. Validation

| Check | Result |
| --- | --- |
| Uncorrected S, τ, Var(S), Z, p and Sen's slope vs `pymannkendall`; least-squares slope and SE vs `scipy` | Identical to floating-point precision |
| Exact AR(1) Var(S) vs 6,000 simulated series | Within 6% (the Monte Carlo error) |
| False alarms, 2,000 AR(1) series per setting, n = 20 and 30 | 3.5–4.1% at r₁ = 0.3 (target ≤ 5%); 4.4–4.7% at r₁ = 0.5 (target ≤ 7%) |
| 95% interval coverage of a synthetic trend | 91–98% |
| Difference test, correlation −0.5 to 0.95 | 3.7–4.8% false alarms |
| "Speeding up" claims for a straight trend with AR(1) noise, n = 15–45 | ≤ 3.3% at r₁ = 0.3, ≤ 4.8% at r₁ = 0.5; real acceleration found in > 90% of 45-year records |
| Vectorised cell engine vs per-series engine | Same slope and p |
| GISTEMP global series vs NASA GLB.Ts+dSST (1880–2025) | r = 0.9997, mean absolute difference 0.008 °C, warming since 1975 of 0.209 vs 0.207 °C per decade, same warmest year |
| Readers on fake files in each product's layout | Orientation, units, fills and dateline wrap correct |
| Exported notebook vs app | Every number reproduced |

Still to do once Earthdata access is configured: regional IMERG and MERRA-2 series against NASA Giovanni area
averages for the test box (targets r ≥ 0.98 and mean difference within 5%), on the test data and again on
the full download.

## 7. Limitations

A trend is not a cause. Records of 20–25 years detect only large trends against year-to-year variability, and
the verdict says so. Reanalysis and land-model variables (MERRA-2, GLDAS) are model estimates constrained by
observations. Coverage changes can bias regional means, which is why coverage is reported. The AR(1) model may
understate long-memory variability (for example deep soil moisture or ocean heat), so fragile and borderline
results should be read with care.

## References

- Benjamini, Y. & Hochberg, Y. (1995). JRSS B 57, 289–300. doi:10.1111/j.2517-6161.1995.tb02031.x
- Gilbert, R. O. (1987). *Statistical Methods for Environmental Pollution Monitoring*. Van Nostrand Reinhold.
- Hamed, K. H. & Rao, A. R. (1998). A modified Mann–Kendall trend test for autocorrelated data. *J. Hydrol.* 204, 182–196.
- Hirsch, R. M., Slack, J. R. & Smith, R. A. (1982). *Water Resour. Res.* 18, 107–121. doi:10.1029/WR018i001p00107
- Lenssen, N. et al. (2019). *J. Geophys. Res. Atmos.* 124, 6307–6326. doi:10.1029/2018JD029522
- Loomis, B. D., Luthcke, S. B. & Sabaka, T. J. (2019). *J. Geodesy* 93, 1381–1398. doi:10.1007/s00190-019-01252-y
- Santer, B. D. et al. (2000). *J. Geophys. Res.* 105, 7337–7356. doi:10.1029/1999JD901105
- Sen, P. K. (1968). *JASA* 63, 1379–1389. doi:10.1080/01621459.1968.10480934
- van Giersbergen, N. P. A. (2005). *Economics Letters* 89, 75–82. doi:10.1016/j.econlet.2005.05.013
- Weatherhead, E. C. et al. (1998). *J. Geophys. Res.* 103, 17149–17161. doi:10.1029/98JD00995
- Wilks, D. S. (2016). *Bull. Amer. Meteor. Soc.* 97, 2263–2273. doi:10.1175/BAMS-D-15-00267.1

The product DOIs are listed in the app's *Method & data* page and in `src/megavir/catalog/__init__.py`.
