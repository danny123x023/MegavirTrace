# MegavirTrace: honest regional trend detection from NASA Earth-observation records

*Methods paper, draft.* Team Space Pirates Paradigm, NASA Space Apps Challenge 2026.

## Abstract

MegavirTrace answers four questions for any region on Earth, for 31 NASA variables: what is changing, where,
how much, and whether the change is significant. It is built around three commitments. Significance is
claimed only when two different tests agree after correction for serial correlation, and false alarms are
measured by Monte Carlo rather than assumed. Every number comes from one deterministic engine and can be
recomputed from an exported notebook. The verdict is written from fixed templates, never by a language model.
Against NASA's official GISTEMP global series, our pipeline reproduces the annual means with r = 0.9997 and
the 1975–present warming rate within 0.002 °C per decade.

## 1. Data

Twenty-three NASA products feed one monthly store of 31 variables (Table 1 of the design document). The first
eleven are OMI OMNO2d v004, GLDAS Noah 2.1, GPM IMERG V07, MiCASA v1, MODIS MOD13C2 v061, NASA-SSH v1, MERRA-2
M2SMNXSLV and M2TMNXSLV, the GSFC GRACE/GRACE-FO mascons, AIRS AIRS3STM v7 and GISTEMP v4.

Six more were added next (MODIS land surface temperature and snow cover, MERRA-2 aerosols, CERES EBAF energy
budget, NSIDC-0051 sea ice and OCO-2 GEOS XCO₂), and six after a survey of 18 data portals: three more MERRA-2
collections (M2TMNXRAD cloud cover and sunshine, M2TMNXLND snow water, M2TMNXFLX wind speed, plus ozone and water
vapour from M2TMNXSLV), GPCP V3.3 rainfall since 1983, SMAP RSS V6 sea surface salinity and MODIS-Aqua L3m
chlorophyll. CERES comes as one file for the whole record, MODIS snow as HDF4
without OPeNDAP, and sea ice on a 25 km polar stereographic grid. Sea-ice pixel centres are converted to latitude
and longitude with the ellipsoidal inverse projection (Snyder 1987, Hughes ellipsoid, true scale at 70°; checked
against NSIDC's published grid corners) and averaged into the 0.5° cells that contain them. Poleward of about
78° a 0.5° cell is narrower than a pixel, so cells that hold no pixel centre take the value of the pixel that
contains the cell's centre. The disc around the North Pole that the satellites never see (flag 251) is counted as
ice, as in NSIDC's Sea Ice Index: it shrank from 1.2 to 0.3 to 0.03 million km² with each new sensor, and left
missing it made early years read low (the Arctic September decline came out about 8% too small, with a step in
1987).

Fields are regridded conservatively to a common 0.5° grid. AIRS and CERES keep their 1° grids, GISTEMP its 2°
grid, and SMAP salinity is stored at 0.25°; land masks exist for every stored grid.
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
fraction for land-only or sea-only variables. The monthly regional value is formed from anomalies, as for
GISTEMP and HadCRUT (Hansen & Lebedeff 1987; Jones et al. 1999): each cell's departure from its own mean for that
calendar month is averaged over the cells with data, and the weighted mean of the cells' calendar-month means is
added back. A change in which part of the region has data then does not show up as a trend: for chlorophyll in the
North China Plain preset, where coverage ranges from 11% to 88%, averaging raw values gave +0.044 mg m⁻³ per decade
and anomalies give −0.065 (neither significant). Where every cell has data the two are identical. The *coverage*
is the share of the region's weight that had data. Months with coverage below 50% are treated as missing, and the
lowest coverage used is reported as a caveat when it is below 95%.

Monthly values become:
- **yearly values:** a year needs at least 10 of 12 months, and its value is the 12-month climatological mean
  plus the mean anomaly of the months present, so a missing winter month does not bias the year. Where some
  calendar months are never observed over the region (polar night for ocean colour), years are built from the
  k months that are and need the same share of them (⌈10k/12⌉ of k, with k ≥ 3); the verdict names those
  months, and a yearly total (rainfall) is then the total over them;
- **seasonal values:** all 3 months are needed, and December belongs to the following DJF;
- **monthly anomalies:** each month minus its calendar month's mean over the chosen years (so the baseline moves
  a little when the year range changes; the Explore page says so beside the view switch). The chart shows the
  months, but the tests use their yearly means. Neighbouring months, and the months of one El Niño year, are not
  independent: with month-to-month memory plus a slow year-to-year swing, a correction for one-month memory
  (the seasonal Mann–Kendall test with an AR(1) fitted at one month) called 18–31% of trend-free series
  significant. Under AR(1) noise the monthly and yearly-mean slopes carry about the same information, so
  little is lost.

## 3. Trend tests

Let *n* be the number of values and r̂₁ the lag-1 autocorrelation of the least-squares residuals, computed
using only neighbours exactly one step apart. This estimate is biased low: by about (2 + 5r₁)/n in long records
(the (2 + 4r₁)/n of van Giersbergen 2005 for the least-squares estimator, plus r₁/n because the ratio divides by
all n squared residuals), and by more at high r₁ in short records (it averages 0.56 at r₁ = 0.9 and n = 25). We
simulated E[r̂₁ | r₁, n] for exactly this estimator (20,000 series per point, n = 6–200, r₁ = −0.5 to 0.99) and
invert it; beyond n = 200 the large-n form r₁ = (n r̂₁ + 2)/(n − 5) is used. The result is clipped to [0, 0.95]
for the corrections.

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

**Sen's slope** is the headline rate, with Gilbert's (1987) interval computed from the corrected Var(S) and the
same t quantile as the Mann–Kendall test it inverts. With the normal quantile the interval was narrower than the
test (87–92% coverage at r₁ = 0.5), and a few "no clear trend" verdicts showed a 95% range that excluded zero.
When the record holds very few independent values (the t quantile with n_eff − 2 degrees of freedom is then
large), the interval has no limit: about 9–13% of trend-free AR(1) records of 20–30 years at r₁ ≥ 0.7. The
verdict then says that no meaningful 95% range can be given, rather than printing −∞ to +∞.

**Agreement rule.** "Significant" requires p < 0.05 in both tests, and the least-squares slope, Sen's slope
and S must have the same sign.

**Detectability.** Following Weatherhead et al. (1998), a trend ω needs about
n* = [3.3 σ_N √(12/k) / |ω| · √((1 + φ)/(1 − φ))]^{2/3} years to be detected, where k is the number of values
per year. Weatherhead's formula is written for monthly data; with yearly values the slope variance scales by
12. A non-significant verdict reports how many more years the record would need. ω is the headline Sen's slope
and σ_N the least-squares residual scatter (φ is r₁): the formula is written for a least-squares slope, and
using the reported rate answers how long a record would need to be to detect the rate the verdict states.

**Percentage points.** For quantities measured in % (sea ice concentration, snow cover, cloud cover), rates,
differences and departures are in percentage points: a fall from 60% to 57% is 3 points (a 5% relative fall).
Verdicts write "percentage points", tiles and maps "pp", and the AI check rejects "% per decade".

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

The same agreement rule runs, vectorised, on every cell's yearly (or seasonal) series; in the monthly views, on
the yearly means of each cell's monthly anomalies. Each cell gets Sen's slope, the tie-corrected Mann–Kendall test
and least squares with the same memory correction and t reference, and its p is the larger of the two when the
signs agree; a cell too persistent to test (n_eff ≤ 3) gets no p and does not enter the false-discovery step. For speed, the Sen median uses
partitioning for complete cells and sorting for cells with gaps. Benjamini–Hochberg q-values are computed
across the region's cells, and a cell passes when q ≤ 2α. Wilks (2016) shows that controlling the FDR at
α_FDR = 2α keeps the field-wide false-alarm rate near α for spatially correlated fields. Because which cells
pass depends on the region tested, the map says so.

## 5. Comparing two regions

The test runs on the trend of the year-by-year difference A − B (Santer et al. 2000). Shared variability
cancels, so correlated regions are not under-tested and anti-correlated ones are not over-tested. We report
the difference per decade, its 95% interval, the Mann–Kendall and least-squares p-values of the difference
(both must pass; where one p is shown, it is the larger), and the smallest difference the record could detect:
(t₀.₉₇₅ + t₀.₈₀) × SE_adj, for 80% power.

## 6. Moves together: relationships between variables

To ask whether two variables rise and fall together in one place, each regional monthly series becomes
anomalies (seasonal cycle removed) and is detrended. Without this, shared seasons and trends make almost any
two series correlate. We then compute the correlation r_k with variable B shifted k months after A, for
|k| ≤ L (L ≤ 24).

Neighbouring months are alike, and removing monthly means leaves its own pattern (correlation 12, 24 and
36 months apart). The variance of r for unrelated series is therefore taken from Bartlett's formula,
Var(r) = (1 + 2 Σ_j ρ_A(j) ρ_B(j)) / n, summed to 36 months, with 13 degrees of freedom (12 monthly means and the
trend) removed from n once. The lag-1 terms use a bias correction measured by simulation: r₁ = (n r̂₁ + 1)/(n − 5.5). The
strongest lag's p-value is multiplied by the number of lags tried (Bonferroni).

A first version with only the lag-1 (Bretherton et al. 1999) effective sample size gave 6–9% false claims for
unrelated series. The version above gives at most 3.5% (n = 120 and 240 months, r₁ = 0–0.9) and finds a real
3-month lead every time. Results are always labelled "related, not caused by".

Bretherton, C. S., Widmann, M., Dymnikov, V. P., Wallace, J. M. & Bladé, I. (1999). *J. Climate* 12,
1990–2009. doi:10.1175/1520-0442(1999)012<1990:TENOSD>2.0.CO;2

## 7. Ground versus satellite: NASA GLOBE

For temperature and rainfall, observations from the GLOBE Program (schools and citizen scientists) for the
same region are fetched from the GLOBE API. Air temperature uses the daily high and low; precipitation uses
rain-gauge accumulations and the days they cover.

The GLOBE values become a regional monthly series:
- each site-month needs readings on at least 10 days (temperature), or gauge readings covering at least
  20 days, scaled to the whole month (rain);
- the regional value is the mean over the sites that qualify that month, and only sites inside the region's
  outline are used.

Both series become monthly anomalies (each month minus that calendar month's mean over the shared months), and
we report their correlation. Over Texas, 18 sites and 29,862 readings from 2012–2026 track GISTEMP with
r = 0.89 over 178 months. GLOBE values are point measurements by volunteers at changing sites, so they are
shown as context and never enter the trend tests.

## 8. Climate projections beside the observed trend

For temperature (tas, tasmax, tasmin) and rainfall (pr), NASA NEX-GDDP-CMIP6 projections (bias-corrected,
downscaled to 0.25°) give context for the observed trend. The sample is documented and small, because each
yearly daily file must be read on the NCCS THREDDS server (13–16 s per request):

- 5 models with a wide spread of climate sensitivity (ACCESS-CM2, CESM2, MIROC6, MPI-ESM1-2-HR, UKESM1-0-LL);
- baseline years 1995, 2000, 2005 and 2010 from each model's historical run;
- years 2030, 2050, 2070 and 2090 under SSP2-4.5 and SSP5-8.5.

Each file is subset to the region's box and averaged with cos(latitude) weights over the box and the year.
Each model's change is measured from its own baseline (rainfall in percent), which removes model biases. The
ensemble median and range are reported. The observed series is shown as its change from its mean over every
observed year in 1995–2010 (at least four; IMERG rainfall, which starts in mid-2000, uses 2001–2010), and only for
yearly values, because the projections are yearly means. The model results are stored per variable and box; the
observed line is added from the analysis being viewed, so a summer series or an older data version is never drawn
beside them.

The plain-language summary comes from fixed templates. For the Gulf Coast test box, around 2090 the models give
+2.9 °C (range +1.4 to +4.9) under SSP2-4.5 and +4.9 °C (+3.7 to +5.6) under SSP5-8.5, compared with 1995–2010.
Single sample years include natural variability, so the ranges matter more than the medians. Projections are
never part of the trend tests.

## 9. Validation

| Check | Result |
| --- | --- |
| Uncorrected S, τ, Var(S), Z, p and Sen's slope vs `pymannkendall`; least-squares slope and SE vs `scipy` | Identical to floating-point precision |
| Exact AR(1) Var(S) vs 6,000 simulated series | Within 6% (the Monte Carlo error) |
| False alarms, 2,000 AR(1) series per setting, n = 20 and 30 | 4.0–4.1% at r₁ = 0.3 (target ≤ 5%); 4.4–4.8% at 0.5 (target ≤ 7%); 5.0–5.5% at 0.7 (target ≤ 6%); 4.4–5.8% at 0.8 and 5.8–6.8% at 0.9 (gated at ≤ 7%; see Limitations) |
| Monthly views: month-to-month memory 0.5 plus a year-to-year swing, 25 years, 1,000 series | 2.0% with an uncorrelated swing, 4.0% with persistence 0.5 (target ≤ 7%); the earlier one-month correction gave 18–31% |
| 95% interval coverage of a synthetic trend (Sen's interval, testable records) | 95–97.5% at r₁ ≤ 0.3; 93–96% at 0.5 (was 87.5–92% with the normal quantile); 85–95% at 0.7 |
| Difference test, correlation −0.5 to 0.95 | 3.7–4.8% false alarms |
| Moves together: unrelated series sharing a season and a trend, 25 lags searched | ≤ 3.5% false claims; a real 3-month lead found at the right lag every time |
| "Speeding up" claims for a straight trend with AR(1) noise, n = 15–45 | ≤ 3.3% at r₁ = 0.3, ≤ 4.8% at r₁ = 0.5; real acceleration found in > 90% of 45-year records |
| Vectorised cell engine vs per-series engine (ties included) | Same slope and joint p |
| GISTEMP global series vs NASA GLB.Ts+dSST (1880–2025) | r = 0.9997, mean absolute difference 0.008 °C, warming since 1975 of 0.209 vs 0.207 °C per decade, same warmest year |
| Readers on fake files in each product's layout | Orientation, units, fills and dateline wrap correct |
| MERRA-2 air temperature vs NASA Giovanni, test box, 36 months | r = 0.9998, mean difference 1.6% |
| IMERG rainfall vs NASA Giovanni, test box, 108 months | r = 0.995, mean difference 1.9% |
| Exported notebook vs app | Every number reproduced |

**NASA Giovanni.** Giovanni's time-series service answers one grid point at a time, from the product's native
grid (MERRA-2 is served hourly, so its monthly means are formed from the hours). We average a 3 × 3 grid of
points across the test box, weighted by cos(latitude), and compare with our stored, regridded box mean.
MERRA-2 air temperature, Oct 2023 – Sep 2026: r = 0.9998, mean difference 1.6% (targets r ≥ 0.98, within 5%).
IMERG rainfall, Oct 2016 – Sep 2025 (108 months, 25 points): r = 0.995, mean difference 1.9%. A re-import that
reproduces the same values exactly keeps its check.

## 10. Limitations

A trend is not a cause. Records of 20–25 years detect only large trends against year-to-year variability, and
the verdict says so. Reanalysis and land-model variables (MERRA-2, GLDAS) are model estimates constrained by
observations. Averaging anomalies keeps coverage changes from creating trends, but a region with little coverage
is still represented only by its observed part, which is why coverage is reported. The AR(1) model may
understate long-memory variability (for example deep soil moisture or ocean heat), so fragile and borderline
results should be read with care. Its blind spot is a mix of fast and slow noise: month-to-month memory 0.5
plus a slow yearly swing with persistence 0.7 gives 7.7% false alarms in 25-year records, and very persistent
yearly series (r₁ = 0.9) give 5.8–6.8%. A record also needs at least 8 years with enough months: OCO-2 GEOS
XCO₂ (January 2015 to February 2022, the end of the product) holds only 7, so the app says it cannot be tested
instead of giving a verdict.

## References

- Benjamini, Y. & Hochberg, Y. (1995). JRSS B 57, 289–300. doi:10.1111/j.2517-6161.1995.tb02031.x
- Gilbert, R. O. (1987). *Statistical Methods for Environmental Pollution Monitoring*. Van Nostrand Reinhold.
- Hansen, J. & Lebedeff, S. (1987). *J. Geophys. Res.* 92, 13345–13372. doi:10.1029/JD092iD11p13345
- Hamed, K. H. & Rao, A. R. (1998). A modified Mann–Kendall trend test for autocorrelated data. *J. Hydrol.* 204, 182–196.
- Hirsch, R. M., Slack, J. R. & Smith, R. A. (1982). *Water Resour. Res.* 18, 107–121. doi:10.1029/WR018i001p00107
- Jones, P. D., New, M., Parker, D. E., Martin, S. & Rigor, I. G. (1999). *Rev. Geophys.* 37, 173–199. doi:10.1029/1999RG900002
- Lenssen, N. et al. (2019). *J. Geophys. Res. Atmos.* 124, 6307–6326. doi:10.1029/2018JD029522
- Loomis, B. D., Luthcke, S. B. & Sabaka, T. J. (2019). *J. Geodesy* 93, 1381–1398. doi:10.1007/s00190-019-01252-y
- Snyder, J. P. (1987). *Map Projections: A Working Manual*. USGS Professional Paper 1395.
- Santer, B. D. et al. (2000). *J. Geophys. Res.* 105, 7337–7356. doi:10.1029/1999JD901105
- Sen, P. K. (1968). *JASA* 63, 1379–1389. doi:10.1080/01621459.1968.10480934
- van Giersbergen, N. P. A. (2005). *Economics Letters* 89, 75–82. doi:10.1016/j.econlet.2005.05.013
- Weatherhead, E. C. et al. (1998). *J. Geophys. Res.* 103, 17149–17161. doi:10.1029/98JD00995
- Wilks, D. S. (2016). *Bull. Amer. Meteor. Soc.* 97, 2263–2273. doi:10.1175/BAMS-D-15-00267.1

The product DOIs are listed in the app's *Method & data* page and in `src/megavir/catalog/__init__.py`.
