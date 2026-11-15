"""Variable and dataset catalog (FR1, FR2).

Every DOI below was resolved against NASA CMR (products) or Crossref (papers); see
``scripts/cmr_lookup.py`` and ``tests/test_catalog.py``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Dataset:
    id: str
    product: str  # short name and version
    title: str
    archive: str
    access: str
    login_required: bool
    doi: str | None
    native_grid: str
    stored_grid_deg: float
    record_start: str  # YYYY-MM
    cadence: str
    citation: str
    paper_doi: str | None = None
    expected_download: str = ""


@dataclass(frozen=True)
class Variable:
    id: str
    name: str
    theme: str
    dataset: str
    units: str  # stored monthly units
    domain: str  # "land" | "ocean" | "all"
    agg: str  # how months combine into a year: "mean" | "sum"
    definition: str
    why_it_can_trend: str
    caveat: str
    source_badge: str
    decimals: int = 2
    rising_words: tuple[str, str] = ("rising", "falling")
    status: str = "available"  # "available" | "planned"
    fields: tuple[str, ...] = field(default_factory=tuple)
    year_units: str | None = None  # units of the yearly value when agg == "sum"
    # "monthly" for gappy records (GRACE): whole years drop out of yearly values, months do not
    default_mode: str = "annual"

    def local(self, lang: str = "en") -> dict:
        """Name, definition, why, caveat and direction words in a language (English fallback)."""
        base = {
            "name": self.name,
            "definition": self.definition,
            "why_it_can_trend": self.why_it_can_trend,
            "caveat": self.caveat,
            "rising_words": tuple(self.rising_words),
        }
        if lang == "es":
            from .i18n_es import ES

            base.update({k: v for k, v in ES.get(self.id, {}).items()})
        return base

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rising_words"] = list(self.rising_words)
        es = self.local("es")
        d["i18n"] = {"es": {**es, "rising_words": list(es["rising_words"])}}
        return d


DATASETS: dict[str, Dataset] = {
    d.id: d
    for d in [
        Dataset(
            "omi_no2",
            "OMNO2d v004",
            "OMI/Aura NO2 Cloud-Screened Total and Tropospheric Column L3 Global Gridded 0.25° x 0.25°",
            "NASA GES DISC",
            "OPeNDAP (NO2 field only)",
            True,
            "10.5067/AURA/OMI/DATA3407",
            "0.25° daily",
            0.5,
            "2004-10",
            "daily",
            "Krotkov, N. A., Lamsal, L. N., Marchenko, S. V., et al. (2024), OMI/Aura NO2 Cloud-Screened Total "
            "and Tropospheric Column L3 Global Gridded 0.25 degree x 0.25 degree Ver 5.0, Col 004, Greenbelt, MD, "
            "USA, GES DISC.",
            expected_download="16 GB, 8,025 files",
        ),
        Dataset(
            "gldas",
            "GLDAS_NOAH025_M 2.1",
            "GLDAS Noah Land Surface Model L4 monthly 0.25 x 0.25 degree V2.1",
            "NASA GES DISC",
            "earthaccess",
            True,
            "10.5067/SXAVCZFAQLNO",
            "0.25° monthly",
            0.5,
            "2000-01",
            "monthly",
            "Beaudoing, H. and M. Rodell, NASA/GSFC/HSL (2020), GLDAS Noah Land Surface Model L4 monthly "
            "0.25 x 0.25 degree V2.1, Greenbelt, Maryland, USA, GES DISC.",
            expected_download="7.5 GB",
        ),
        Dataset(
            "imerg",
            "GPM_3IMERGM V07",
            "GPM IMERG Final Precipitation L3 1 month 0.1 degree x 0.1 degree V07",
            "NASA GES DISC",
            "earthaccess",
            True,
            "10.5067/GPM/IMERG/3B-MONTH/07",
            "0.1° monthly",
            0.5,
            "2000-06",
            "monthly",
            "Huffman, G. J., E. F. Stocker, D. T. Bolvin, E. J. Nelkin, J. Tan (2023), GPM IMERG Final "
            "Precipitation L3 1 month 0.1 degree x 0.1 degree V07, Greenbelt, MD, GES DISC.",
            expected_download="5.9 GB",
        ),
        Dataset(
            "micasa",
            "MiCASA v1",
            "MiCASA Monthly NPP Rh ATMC NEE FIRE FUEL Fluxes 0.1 degree x 0.1 degree",
            "NASA NCCS (public copy); also NASA GES DISC",
            "public HTTPS",
            False,
            "10.5067/UCFEAAIDIUEQ",
            "0.1° monthly",
            0.5,
            "2001-01",
            "monthly",
            "Weir, B., Webb, A., Ott, L. (2024), MiCASA Monthly NPP Rh ATMC NEE FIRE FUEL Fluxes 0.1 degree x "
            "0.1 degree, Greenbelt, MD, USA, GES DISC.",
            expected_download="4.9 GB",
        ),
        Dataset(
            "modis_ndvi",
            "MOD13C2 v061",
            "MODIS/Terra Vegetation Indices Monthly L3 Global 0.05Deg CMG V061",
            "NASA LP DAAC",
            "OPeNDAP (NDVI only)",
            True,
            "10.5067/MODIS/MOD13C2.061",
            "0.05° monthly",
            0.5,
            "2000-02",
            "monthly",
            "Didan, K. (2021). MODIS/Terra Vegetation Indices Monthly L3 Global 0.05Deg CMG V061. "
            "NASA Land Processes Distributed Active Archive Center, Sioux Falls, South Dakota, USA.",
            expected_download="2.8 GB",
        ),
        Dataset(
            "nasa_ssh",
            "NASA_SSH_REF_SIMPLE_GRID_V1",
            "NASA-SSH Simple Gridded Sea Surface Height from Standardized Reference Missions Only Version 1",
            "NASA PO.DAAC",
            "earthaccess",
            True,
            "10.5067/NSREF-SG0V1",
            "0.5° weekly (7-day)",
            0.5,
            "1992-11",
            "weekly",
            "Willis, J. K., Fournier, S., Marlis, K., Killett, E., Sanchez, J. (2025). NASA-SSH Simple Gridded "
            "Sea Surface Height from Standardized Reference Missions Only Version 1. PO.DAAC, CA, USA.",
            expected_download="1.9 GB",
        ),
        Dataset(
            "merra2_stat",
            "M2SMNXSLV 5.12.4",
            "MERRA-2 statM_2d_slv_Nx: 2d, Monthly, Aggregated Statistics, Single-Level Diagnostics",
            "NASA GES DISC",
            "OPeNDAP (T2MMAX, T2MMIN, TPRECMAX)",
            True,
            "10.5067/KVIMOMCUO83U",
            "0.5° x 0.625° monthly",
            0.5,
            "1980-01",
            "monthly",
            "Global Modeling and Assimilation Office (GMAO) (2015), MERRA-2 statM_2d_slv_Nx: 2d, Monthly, "
            "Aggregated Statistics, Single-Level, Assimilation, Single-Level Diagnostics V5.12.4, "
            "Greenbelt, MD, USA, GES DISC.",
            expected_download="0.9 GB",
        ),
        Dataset(
            "grace",
            "GSFC GRACE/GRACE-FO mascons RL06v2.0",
            "NASA GSFC global GRACE and GRACE-FO mascons, 0.5° gridded",
            "NASA GSFC",
            "public HTTPS",
            False,
            None,
            "1° equal-area mascons, delivered on 0.5°",
            0.5,
            "2002-04",
            "monthly (with gaps)",
            "Loomis, B. D., Luthcke, S. B., & Sabaka, T. J. (2019). Regularization and error characterization "
            "of GRACE mascons. Journal of Geodesy, 93, 1381–1398.",
            paper_doi="10.1007/s00190-019-01252-y",
            expected_download="0.5 GB",
        ),
        Dataset(
            "merra2_slv",
            "M2TMNXSLV 5.12.4",
            "MERRA-2 tavgM_2d_slv_Nx: 2d, Monthly mean, Time-Averaged, Single-Level Diagnostics",
            "NASA GES DISC",
            "OPeNDAP (T2M, TO3, TQV only)",
            True,
            "10.5067/AP1B0BA5PD2K",
            "0.5° x 0.625° monthly",
            0.5,
            "1980-01",
            "monthly",
            "Global Modeling and Assimilation Office (GMAO) (2015), MERRA-2 tavgM_2d_slv_Nx: 2d, Monthly "
            "mean, Time-Averaged, Single-Level, Assimilation, Single-Level Diagnostics V5.12.4, Greenbelt, "
            "MD, USA, GES DISC.",
            expected_download="0.9 GB",
        ),
        Dataset(
            "airs",
            "AIRS3STM v7.0",
            "Aqua/AIRS L3 Monthly Standard Physical Retrieval (AIRS-only) 1 degree x 1 degree V7.0",
            "NASA GES DISC",
            "OPeNDAP (SurfSkinTemp_A, SurfSkinTemp_D)",
            True,
            "10.5067/UBENJB9D3T2H",
            "1° monthly",
            1.0,
            "2002-09",
            "monthly",
            "AIRS project (2019), Aqua/AIRS L3 Monthly Standard Physical Retrieval (AIRS-only) 1 degree x "
            "1 degree V7.0, Greenbelt, MD, USA, GES DISC.",
            expected_download="0.15 GB",
        ),
        Dataset(
            "gistemp",
            "GISTEMP v4",
            "GISS Surface Temperature Analysis v4 (1200 km smoothing, GHCNv4 + ERSSTv5)",
            "NASA GISS",
            "public HTTPS",
            False,
            None,
            "2° monthly",
            2.0,
            "1880-01",
            "monthly",
            "GISTEMP Team (2025): GISS Surface Temperature Analysis (GISTEMP), version 4. NASA Goddard "
            "Institute for Space Studies. Lenssen, N., et al. (2019), Improvements in the GISTEMP "
            "uncertainty model, J. Geophys. Res. Atmos., 124, 6307–6326.",
            paper_doi="10.1029/2018JD029522",
            expected_download="25 MB",
        ),
    ]
}

# FR2: six more variables.  Code ready; all need a NASA Earthdata Login to download.
DATASETS.update(
    {
        d.id: d
        for d in [
            Dataset(
                "modis_lst",
                "MOD11C3 v061",
                "MODIS/Terra Land Surface Temperature/Emissivity Monthly L3 Global 0.05Deg CMG V061",
                "NASA LP DAAC",
                "OPeNDAP (LST_Day_CMG, LST_Night_CMG)",
                True,
                "10.5067/MODIS/MOD11C3.061",
                "0.05° monthly",
                0.5,
                "2000-02",
                "monthly",
                "Wan, Z., Hook, S., Hulley, G. (2021). MODIS/Terra Land Surface Temperature/Emissivity Monthly L3 "
                "Global 0.05Deg CMG V061. NASA Land Processes Distributed Active Archive Center.",
                expected_download="about 1.5 GB (2 fields)",
            ),
            Dataset(
                "modis_snow",
                "MOD10CM v61",
                "MODIS/Terra Snow Cover Monthly L3 Global 0.05Deg CMG V061",
                "NASA NSIDC DAAC",
                "whole HDF4 files (no OPeNDAP), read with pyhdf",
                True,
                "10.5067/MODIS/MOD10CM.061",
                "0.05° monthly",
                0.5,
                "2000-03",
                "monthly",
                "MODIS/Terra Snow Cover Monthly L3 Global 0.05Deg CMG V061. NASA National Snow and Ice Data Center "
                "Distributed Active Archive Center.",
                expected_download="about 3 GB",
            ),
            Dataset(
                "merra2_aer",
                "M2TMNXAER 5.12.4",
                "MERRA-2 tavgM_2d_aer_Nx: 2d, Monthly mean, Time-averaged, Single-Level, Aerosol Diagnostics",
                "NASA GES DISC",
                "OPeNDAP (TOTEXTTAU only)",
                True,
                "10.5067/FH9A0MLJPC7N",
                "0.5° x 0.625° monthly",
                0.5,
                "1980-01",
                "monthly",
                "Global Modeling and Assimilation Office (GMAO) (2015), MERRA-2 tavgM_2d_aer_Nx: 2d,Monthly mean,"
                "Time-averaged,Single-Level,Assimilation,Aerosol Diagnostics V5.12.4, Greenbelt, MD, USA, GES DISC.",
                expected_download="about 0.3 GB",
            ),
            Dataset(
                "ceres_ebaf",
                "CERES EBAF Ed4.2.1",
                "CERES Energy Balanced and Filled (EBAF) TOA and Surface Monthly means, Edition 4.2.1",
                "NASA LaRC ASDC",
                "OPeNDAP (toa_net_all_mon; one file for the whole record)",
                True,
                "10.5067/TERRA-AQUA-NOAA20/CERES/EBAF_L3B004.2.1",
                "1° monthly",
                1.0,
                "2000-03",
                "monthly",
                "NASA/LARC/SD/ASDC. CERES Energy Balanced and Filled (EBAF) TOA and Surface Monthly means data in "
                "netCDF Edition 4.2.1. NASA Langley Atmospheric Science Data Center.",
                expected_download="about 0.1 GB",
            ),
            Dataset(
                "nsidc_seaice",
                "NSIDC-0051 v2",
                "Sea Ice Concentrations from Nimbus-7 SMMR and DMSP SSM/I-SSMIS Passive Microwave Data V002",
                "NASA NSIDC DAAC",
                "whole monthly netCDF files (north and south), 25 km polar stereographic",
                True,
                "10.5067/MPYG15WAA4WX",
                "25 km polar stereographic, binned to 0.5°",
                0.5,
                "1978-11",
                "monthly",
                "Sea Ice Concentrations from Nimbus-7 SMMR and DMSP SSM/I-SSMIS Passive Microwave Data V002. NASA "
                "National Snow and Ice Data Center Distributed Active Archive Center.",
                expected_download="about 0.6 GB (monthly files)",
            ),
            Dataset(
                "oco2",
                "OCO2_GEOS_L3CO2_MONTH 10r",
                "OCO-2 GEOS Level 3 monthly, 0.5x0.625 assimilated CO2 V10r",
                "NASA GES DISC",
                "OPeNDAP (XCO2 only)",
                True,
                "10.5067/BGFIODET3HZ8",
                "0.5° x 0.625° monthly",
                0.5,
                "2015-01",
                "monthly",
                "Brad Weir, Lesley Ott and OCO-2 Science Team (2022), OCO-2 GEOS Level 3 monthly, 0.5x0.625 "
                "assimilated CO2 V10r, Greenbelt, MD, USA, GES DISC.",
                expected_download="about 0.05 GB",
            ),
        ]
    }
)

# Nothing is planned any more; kept so the API shape stays the same.
PLANNED_DATASETS: dict[str, Dataset] = {}


# Added 2026-11-15 (survey of NASA and partner archives): DOIs, titles and citations from NASA CMR.
DATASETS.update(
    {
        d.id: d
        for d in [
            Dataset(
                "merra2_rad",
                "M2TMNXRAD 5.12.4",
                "MERRA-2 tavgM_2d_rad_Nx: 2d, Monthly mean, Time-Averaged, Single-Level, Assimilation, Radiation Diagnostics",
                "NASA GES DISC",
                "OPeNDAP (CLDTOT, SWGDN only)",
                True,
                "10.5067/OU3HJDS973O0",
                "0.5° x 0.625° monthly",
                0.5,
                "1980-01",
                "monthly",
                "Global Modeling and Assimilation Office (GMAO) (2015), MERRA-2 tavgM_2d_rad_Nx: 2d, Monthly mean, "
                "Time-Averaged, Single-Level, Assimilation, Radiation Diagnostics V5.12.4, Greenbelt, MD, USA, GES DISC.",
                paper_doi="10.1175/JCLI-D-16-0758.1",
                expected_download="about 0.6 GB",
            ),
            Dataset(
                "merra2_lnd",
                "M2TMNXLND 5.12.4",
                "MERRA-2 tavgM_2d_lnd_Nx: 2d, Monthly mean, Time-Averaged, Single-Level, Assimilation, Land Surface Diagnostics",
                "NASA GES DISC",
                "OPeNDAP (SNOMAS only)",
                True,
                "10.5067/8S35XF81C28F",
                "0.5° x 0.625° monthly",
                0.5,
                "1980-01",
                "monthly",
                "Global Modeling and Assimilation Office (GMAO) (2015), MERRA-2 tavgM_2d_lnd_Nx: 2d, Monthly mean, "
                "Time-Averaged, Single-Level, Assimilation, Land Surface Diagnostics V5.12.4, Greenbelt, MD, USA, GES DISC.",
                paper_doi="10.1175/JCLI-D-16-0758.1",
                expected_download="about 0.3 GB",
            ),
            Dataset(
                "merra2_flx",
                "M2TMNXFLX 5.12.4",
                "MERRA-2 tavgM_2d_flx_Nx: 2d, Monthly mean, Time-Averaged, Single-Level, Assimilation, Surface Flux Diagnostics",
                "NASA GES DISC",
                "OPeNDAP (SPEED only)",
                True,
                "10.5067/0JRLVL8YV2Y4",
                "0.5° x 0.625° monthly",
                0.5,
                "1980-01",
                "monthly",
                "Global Modeling and Assimilation Office (GMAO) (2015), MERRA-2 tavgM_2d_flx_Nx: 2d, Monthly mean, "
                "Time-Averaged, Single-Level, Assimilation, Surface Flux Diagnostics V5.12.4, Greenbelt, MD, USA, GES DISC.",
                paper_doi="10.1175/JCLI-D-16-0758.1",
                expected_download="about 0.3 GB",
            ),
            Dataset(
                "gpcp",
                "GPCPMON V3.3",
                "GPCP Precipitation Level 3 Monthly 0.5-Degree V3.3",
                "NASA GES DISC",
                "OPeNDAP (sat_gauge_precip only)",
                True,
                "10.5067/MEASURES/GPCP/DATA306",
                "0.5° monthly",
                0.5,
                "1983-01",
                "monthly",
                "Huffman, G. J., A. Behrangi, D. T. Bolvin and E. J. Nelkin (2025), GPCP Version 3.3 Satellite-Gauge (SG) "
                "Combined Precipitation Data Set, Version 3.3, Greenbelt, MD, USA, GES DISC.",
                expected_download="about 0.4 GB",
            ),
            Dataset(
                "smap_sss",
                "SMAP_RSS_L3_SSS_SMI_MONTHLY_V6 6.0",
                "RSS SMAP Level 3 Sea Surface Salinity Standard Mapped Image Monthly V6.0 Validated Dataset",
                "NASA PO.DAAC",
                "OPeNDAP (sss_smap only)",
                True,
                "10.5067/SMP60-3SMCS",
                "0.25° monthly (smoothed to about 70 km)",
                0.25,
                "2015-04",
                "monthly",
                "Remote Sensing Systems (2024), SMAP Sea Surface Salinity Products, Version 6.0, Santa Rosa, CA, USA. "
                "Distributed by NASA PO.DAAC.",
                expected_download="about 0.6 GB",
            ),
            Dataset(
                "modis_chl",
                "MODISA_L3m_CHL R2022.0",
                "Aqua MODIS Level-3 Global Mapped Chlorophyll (CHL) Data, version 2022.0",
                "NASA OB.DAAC",
                "earthaccess (whole monthly 9 km files)",
                True,
                "10.5067/AQUA/MODIS/L3M/CHL/2022.0",
                "9 km (1/12°) monthly",
                0.5,
                "2002-07",
                "monthly",
                "NASA Goddard Space Flight Center, Ocean Ecology Laboratory, Ocean Biology Processing Group (2022), "
                "Aqua MODIS Level-3 Global Mapped Chlorophyll (CHL) Data, version 2022.0, NASA OB.DAAC.",
                expected_download="about 3.5 GB",
            ),
        ]
    }
)


def _v(**kw) -> Variable:
    return Variable(**kw)


VARIABLES: dict[str, Variable] = {
    v.id: v
    for v in [
        # ---- Heat --------------------------------------------------------------------
        _v(
            id="air_temp",
            name="Air temperature (2 m)",
            theme="Heat",
            dataset="merra2_slv",
            units="°C",
            domain="all",
            agg="mean",
            fields=("T2M",),
            source_badge="MERRA-2",
            definition="The temperature of the air 2 metres above the ground, averaged over day and night.",
            why_it_can_trend="Greenhouse gases trap more heat; land use, irrigation and cities also change local temperature.",
            caveat="MERRA-2 is a reanalysis: a weather model kept close to observations, not a direct measurement.",
            rising_words=("warming", "cooling"),
        ),
        _v(
            id="daily_high",
            name="Daily high temperature",
            theme="Heat",
            dataset="merra2_stat",
            units="°C",
            domain="all",
            agg="mean",
            fields=("T2MMAX",),
            source_badge="MERRA-2",
            definition="The hottest temperature of each day at 2 m, averaged over the month.",
            why_it_can_trend="Warming, drier soils and fewer clouds raise afternoon highs.",
            caveat="A monthly average of daily highs, not single-day extremes.",
            rising_words=("warming", "cooling"),
        ),
        _v(
            id="nightly_low",
            name="Nightly low temperature",
            theme="Heat",
            dataset="merra2_stat",
            units="°C",
            domain="all",
            agg="mean",
            fields=("T2MMIN",),
            source_badge="MERRA-2",
            definition="The coldest temperature of each day at 2 m (usually near dawn), averaged over the month.",
            why_it_can_trend="Nights often warm faster than days: more water vapour and cloud hold heat in after sunset.",
            caveat="A monthly average of daily lows, not single-night extremes.",
            rising_words=("warming", "cooling"),
        ),
        _v(
            id="ground_temp",
            name="Ground surface temperature",
            theme="Heat",
            dataset="airs",
            units="°C",
            domain="land",
            agg="mean",
            fields=("SurfSkinTemp_A", "SurfSkinTemp_D"),
            source_badge="AIRS · Aqua",
            definition="The temperature of the land surface itself (its 'skin'), seen from space by infrared, day and night averaged.",
            why_it_can_trend="Warming air, drying soil, lost vegetation and new pavement all heat the ground surface.",
            caveat="Only cloud-free views are possible, so very cloudy months have fewer observations; 1° grid.",
            rising_words=("warming", "cooling"),
        ),
        _v(
            id="temp_change",
            name="Surface temperature change",
            theme="Heat",
            dataset="gistemp",
            units="°C",
            domain="all",
            agg="mean",
            fields=("tempanomaly",),
            source_badge="GISTEMP · NASA GISS",
            definition="How much warmer or colder the surface is than the 1951–1980 average, from weather stations and ships.",
            why_it_can_trend="This is the record most used to track global warming since 1880.",
            caveat="Values are departures from a baseline, not temperatures; 2° grid, with sparse stations early on.",
            rising_words=("warming", "cooling"),
        ),
        # ---- Water cycle -------------------------------------------------------------
        _v(
            id="rainfall",
            name="Rainfall",
            theme="Water cycle",
            dataset="imerg",
            units="mm/month",
            domain="all",
            agg="sum",
            fields=("precipitation",),
            source_badge="GPM IMERG",
            year_units="mm/year",
            definition="All rain and snow (as water) falling in a month, merged from many satellites and rain gauges.",
            why_it_can_trend="A warmer atmosphere holds more water, and storm tracks and monsoons can shift.",
            caveat="Rainfall varies a lot from year to year, so trends need long records to stand out.",
            rising_words=("getting wetter", "getting drier"),
            decimals=1,
        ),
        _v(
            id="downpour",
            name="Downpour intensity",
            theme="Water cycle",
            dataset="merra2_stat",
            units="mm/hour",
            domain="all",
            agg="mean",
            fields=("TPRECMAX",),
            source_badge="MERRA-2",
            definition="The heaviest hour of rain in each day, averaged over the month.",
            why_it_can_trend="Warmer air can dump more water at once, so the hardest downpours can intensify.",
            caveat="A reanalysis estimate of hourly rates; local cloudbursts are smoothed over a ~50 km cell.",
            rising_words=("seeing heavier downpours", "seeing lighter downpours"),
            decimals=3,
        ),
        _v(
            id="evapotranspiration",
            name="Evapotranspiration",
            theme="Water cycle",
            dataset="gldas",
            units="mm/month",
            domain="land",
            agg="sum",
            fields=("Evap_tavg",),
            source_badge="GLDAS",
            year_units="mm/year",
            definition="Water returned to the air by evaporation from soil and water and by plants breathing it out.",
            why_it_can_trend="Heat, longer growing seasons, irrigation and drying soils change how much water goes back up.",
            caveat="A land-model estimate driven by observations, not a direct measurement.",
            rising_words=("returning more water to the air", "returning less water to the air"),
            decimals=1,
        ),
        # ---- Soil and land water -----------------------------------------------------
        _v(
            id="topsoil_moisture",
            name="Topsoil moisture (0–10 cm)",
            theme="Soil and land water",
            dataset="gldas",
            units="mm",
            domain="land",
            agg="mean",
            fields=("SoilMoi0_10cm_inst",),
            source_badge="GLDAS",
            definition="Water held in the top 10 cm of soil, as millimetres of water.",
            why_it_can_trend="Less rain, more heat or more irrigation dry or wet the surface soil.",
            caveat="A land-model estimate; it responds quickly to single storms.",
            rising_words=("getting wetter at the surface", "drying out at the surface"),
            decimals=1,
        ),
        _v(
            id="soil_moisture",
            name="Soil moisture (0–100 cm)",
            theme="Soil and land water",
            dataset="gldas",
            units="mm",
            domain="land",
            agg="mean",
            fields=("SoilMoi0_10cm_inst", "SoilMoi10_40cm_inst", "SoilMoi40_100cm_inst"),
            source_badge="GLDAS",
            definition="Water held in the top metre of soil, where most roots are, as millimetres of water.",
            why_it_can_trend="Long dry or wet spells and changes in evaporation build up slowly in deeper soil.",
            caveat="A land-model estimate; deep layers change slowly, so years are strongly linked to each other.",
            rising_words=("getting wetter underground", "drying out underground"),
            decimals=0,
        ),
        _v(
            id="land_water",
            name="Water stored on land",
            theme="Soil and land water",
            dataset="grace",
            units="cm",
            domain="land",
            agg="mean",
            fields=("lwe_thickness",),
            source_badge="GRACE/GRACE-FO",
            definition="All water on and under the land (snow, soil, groundwater, lakes, ice), measured by tiny changes in gravity.",
            why_it_can_trend="Groundwater pumping, melting glaciers and long droughts or wet periods change stored water.",
            caveat="Very coarse (about 300 km features) and shown as a change from a baseline; there is a gap between missions in 2017–2018, so it is analysed month by month.",
            rising_words=("gaining water", "losing water"),
            decimals=1,
            default_mode="monthly",
        ),
        # ---- Air quality -------------------------------------------------------------
        _v(
            id="no2",
            name="Nitrogen dioxide (NO₂)",
            theme="Air quality",
            dataset="omi_no2",
            units="10¹⁵ molecules/cm²",
            domain="all",
            agg="mean",
            fields=("ColumnAmountNO2TropCloudScreened",),
            source_badge="OMI · Aura",
            definition="The amount of nitrogen dioxide, a traffic and industry pollutant, in the air column above the ground.",
            why_it_can_trend="Cleaner engines and power plants lower it; new industry and traffic raise it.",
            caveat="Seen only on cloud-free days; it describes the whole air column, not the air at street level.",
            rising_words=("seeing more NO₂ pollution", "seeing less NO₂ pollution"),
            decimals=2,
        ),
        # ---- Fire --------------------------------------------------------------------
        _v(
            id="fire_carbon",
            name="Fire carbon emissions",
            theme="Fire",
            dataset="micasa",
            units="g C/m²/month",
            domain="land",
            agg="sum",
            fields=("FIRE",),
            source_badge="MiCASA",
            year_units="g C/m²/year",
            definition="Carbon released to the air by burning vegetation, estimated from satellite-seen burned area.",
            why_it_can_trend="Heat, drought, land clearing and fire management change how much burns.",
            caveat="Fire years are very uneven, so trends are hard to detect; a model estimate, not direct measurement.",
            rising_words=("seeing more fire emissions", "seeing less fire emissions"),
            decimals=2,
        ),
        # ---- Vegetation --------------------------------------------------------------
        _v(
            id="ndvi",
            name="Vegetation greenness (NDVI)",
            theme="Vegetation",
            dataset="modis_ndvi",
            units="NDVI",
            domain="land",
            agg="mean",
            fields=("CMG 0.05 Deg Monthly NDVI",),
            source_badge="MODIS · Terra",
            definition="How green and leafy the land looks from space, from −1 to 1 (dense forest is about 0.8).",
            why_it_can_trend="More CO₂, longer seasons and irrigation green the land; drought, fire and clearing brown it.",
            caveat="Greener is not always healthier: crops and invasive plants also raise it.",
            rising_words=("greening", "browning"),
            decimals=3,
        ),
        # ---- Ocean -------------------------------------------------------------------
        _v(
            id="sea_level",
            name="Sea level",
            theme="Ocean",
            dataset="nasa_ssh",
            units="mm",
            domain="ocean",
            agg="mean",
            fields=("ssha",),
            source_badge="NASA-SSH",
            definition="The height of the sea surface measured by satellite radar, as a change from a reference level.",
            why_it_can_trend="Melting ice and warming (expanding) water raise the sea; currents shift it regionally.",
            caveat="Open ocean only: coastal cells are less reliable, and land moving up or down is not included.",
            rising_words=("seeing the sea rise", "seeing the sea fall"),
            decimals=1,
        ),
        _v(
            id="sea_surface_temp",
            name="Sea surface temperature",
            theme="Ocean",
            dataset="airs",
            units="°C",
            domain="ocean",
            agg="mean",
            fields=("SurfSkinTemp_A", "SurfSkinTemp_D"),
            source_badge="AIRS · Aqua",
            definition="The temperature of the sea surface's thin top layer, seen from space by infrared. Frozen "
            "sea is left out: a cell with sea ice that month has no value.",
            why_it_can_trend="The oceans absorb most of the extra heat from greenhouse gases.",
            caveat="Infrared needs at least partly clear skies (the microwave sounder helps see past some cloud), so "
            "very cloudy areas have fewer values; near the ice edge the open-water area changes from year to year; 1° grid.",
            rising_words=("seeing warmer seas", "seeing cooler seas"),
        ),
        # ---- FR2 ---------------------------------------------------------------------
        _v(
            id="land_surface_temp",
            name="Land surface temperature (MODIS)",
            theme="Heat",
            dataset="modis_lst",
            units="°C",
            domain="land",
            agg="mean",
            fields=("LST_Day_CMG", "LST_Night_CMG"),
            source_badge="MODIS · Terra",
            definition="How hot the ground itself is, seen from space by infrared, day and night averaged, at fine detail.",
            why_it_can_trend="Warming air, drier soils, lost vegetation and growing cities all heat the land surface.",
            caveat="Only clear-sky views count, so cloudy months have fewer observations.",
            rising_words=("warming", "cooling"),
        ),
        _v(
            id="snow_cover",
            name="Snow cover",
            theme="Soil and land water",
            dataset="modis_snow",
            units="%",
            domain="land",
            agg="mean",
            fields=("Snow_Cover_Monthly_CMG",),
            source_badge="MODIS · Terra",
            definition="The share of the ground covered by snow in a month, seen from space.",
            why_it_can_trend="Warmer winters and springs shorten the snow season; more winter precipitation can add snow.",
            caveat="Clouds and polar night hide the ground; a cell with no snow all year has nothing to trend.",
            rising_words=("gaining snow cover", "losing snow cover"),
            decimals=1,
        ),
        _v(
            id="aerosols",
            name="Aerosols (haze, dust and smoke)",
            theme="Air quality",
            dataset="merra2_aer",
            units="AOD",
            domain="all",
            agg="mean",
            fields=("TOTEXTTAU",),
            source_badge="MERRA-2",
            definition="How much tiny particles in the air (dust, smoke, sea salt, pollution) dim the sunlight, as optical depth.",
            why_it_can_trend="Cleaner air laws lower it; new industry, fires and dust storms raise it.",
            caveat="A reanalysis estimate guided by satellite observations; 0 is perfectly clear air.",
            rising_words=("getting hazier", "getting clearer"),
            decimals=3,
        ),
        _v(
            id="energy_budget",
            name="Earth's energy budget (net at the top of the atmosphere)",
            theme="Heat",
            dataset="ceres_ebaf",
            units="W/m²",
            domain="all",
            agg="mean",
            fields=("toa_net_all_mon",),
            source_badge="CERES",
            definition="Sunlight absorbed minus heat sent back to space, per square metre: above zero, the place is gaining energy.",
            why_it_can_trend="Greenhouse gases trap outgoing heat; changes in clouds, ice and haze change how much sunlight is absorbed.",
            caveat="Regional values include heat carried in and out by winds and currents; 1° grid.",
            rising_words=("taking in more energy", "taking in less energy"),
            decimals=2,
        ),
        _v(
            id="sea_ice",
            name="Sea ice concentration",
            theme="Ocean",
            dataset="nsidc_seaice",
            units="%",
            domain="ocean",
            agg="mean",
            fields=("ICECON",),
            source_badge="NSIDC · DMSP",
            definition="The share of the sea surface covered by ice, measured by satellite microwave sensors since 1978.",
            why_it_can_trend="Warmer air and water melt sea ice and shorten the frozen season.",
            caveat="Summer melt ponds look like open water. The disc around the North Pole that the satellites never see "
            "(1.2 million km² before 1987, 0.03 million km² now) is counted as ice-covered, as in NSIDC's Sea Ice Index.",
            rising_words=("gaining sea ice", "losing sea ice"),
            decimals=1,
        ),
        _v(
            id="co2",
            name="Carbon dioxide (XCO₂)",
            theme="Air quality",
            dataset="oco2",
            units="ppm",
            domain="all",
            agg="mean",
            fields=("XCO2",),
            source_badge="OCO-2 · GEOS",
            definition="The average amount of carbon dioxide in the whole column of air, in parts per million.",
            why_it_can_trend="Burning fossil fuels adds CO₂ everywhere; regional differences come from plants, fires and winds.",
            caveat="A model assimilation of OCO-2 measurements. The product ends in February 2022, so the record (from "
            "January 2015) holds 7 full years: too short for a trend test here, which needs 8. CO₂ rises almost "
            "everywhere, so local differences are small.",
            rising_words=("seeing more CO₂", "seeing less CO₂"),
            decimals=1,
        ),
        # ---- added 2026-11-15 ----------------------------------------------------------------
        _v(
            id="rainfall_long",
            name="Long-record rainfall",
            theme="Water cycle",
            dataset="gpcp",
            units="mm/month",
            domain="all",
            agg="sum",
            fields=("sat_gauge_precip",),
            source_badge="GPCP",
            year_units="mm/year",
            definition="All rain and snow (as water) falling in a month, from satellites and rain gauges combined, back to 1983.",
            why_it_can_trend="A warmer atmosphere holds more water, and storm tracks and monsoons can shift. This record is about 17 years longer than the main rainfall record, so slow changes are easier to detect.",
            caveat="Coarser (0.5°) than the main rainfall record and updated a few months late; rainfall varies a lot from year to year.",
            rising_words=("getting wetter", "getting drier"),
            decimals=1,
        ),
        _v(
            id="water_vapour",
            name="Water vapour in the air",
            theme="Water cycle",
            dataset="merra2_slv",
            units="mm",
            domain="all",
            agg="mean",
            fields=("TQV",),
            source_badge="MERRA-2",
            definition="All the water vapour in the column of air above a place, as millimetres of water if it all fell as rain.",
            why_it_can_trend="Warmer air holds about 7% more water vapour per °C, so a warming climate moistens the air, and that extra vapour feeds heavier downpours.",
            caveat="A reanalysis estimate guided by satellite and weather-balloon measurements.",
            rising_words=("gaining water vapour", "losing water vapour"),
            decimals=2,
        ),
        _v(
            id="snow_water",
            name="Snow water (snowpack)",
            theme="Soil and land water",
            dataset="merra2_lnd",
            units="mm",
            domain="land",
            agg="mean",
            fields=("SNOMAS",),
            source_badge="MERRA-2",
            definition="How much water is stored in the snow on the ground, as millimetres of melted water.",
            why_it_can_trend="Warmer winters melt snow earlier and turn snow into rain; more winter precipitation can build a deeper snowpack.",
            caveat="A land-model estimate driven by observed weather; ice sheets and glaciers are not modelled as snow, and a place without snow has nothing to trend.",
            rising_words=("gaining snow water", "losing snow water"),
            decimals=1,
        ),
        _v(
            id="cloud_cover",
            name="Cloud cover",
            theme="Sky and air",
            dataset="merra2_rad",
            units="%",
            domain="all",
            agg="mean",
            fields=("CLDTOT",),
            source_badge="MERRA-2",
            definition="The share of the sky covered by clouds in a month, day and night.",
            why_it_can_trend="Warming changes where clouds form; cleaner or dirtier air and shifting storm tracks change them too.",
            caveat="A reanalysis estimate: clouds are among the hardest things for weather models to get right, so treat small trends with care.",
            rising_words=("getting cloudier", "getting less cloudy"),
            decimals=1,
        ),
        _v(
            id="sunshine",
            name="Sunshine at the ground",
            theme="Sky and air",
            dataset="merra2_rad",
            units="W/m²",
            domain="all",
            agg="mean",
            fields=("SWGDN",),
            source_badge="MERRA-2",
            definition="How much sunlight reaches the ground, averaged over day and night, in watts per square metre.",
            why_it_can_trend="Fewer clouds or cleaner air let more sunlight through (brightening); more haze or cloud dims it (dimming).",
            caveat="A reanalysis estimate that depends on its clouds and aerosols, not a direct measurement at the ground.",
            rising_words=("getting sunnier", "getting dimmer"),
            decimals=1,
        ),
        _v(
            id="wind_speed",
            name="Wind speed near the ground",
            theme="Sky and air",
            dataset="merra2_flx",
            units="m/s",
            domain="all",
            agg="mean",
            fields=("SPEED",),
            source_badge="MERRA-2",
            definition="The average speed of the wind near the ground in a month.",
            why_it_can_trend="Shifting storm tracks, the contrast between land and sea, and a changing temperature difference between the poles and the tropics can make winds stronger or weaker.",
            caveat="A reanalysis estimate; changes over the years in the observations it uses can leave small artificial trends.",
            rising_words=("getting windier", "getting calmer"),
            decimals=2,
        ),
        _v(
            id="ozone",
            name="Ozone layer (total ozone)",
            theme="Sky and air",
            dataset="merra2_slv",
            units="DU",
            domain="all",
            agg="mean",
            fields=("TO3",),
            source_badge="MERRA-2",
            definition="How much ozone is in the whole column of air above a place, in Dobson units; most of it is high up, in the ozone layer that blocks harmful UV light.",
            why_it_can_trend="Ozone-destroying chemicals (CFCs) thinned the layer, worst over Antarctica in spring; since they were banned in 1987 it has been slowly recovering.",
            caveat="A reanalysis that assimilates satellite ozone measurements. The Antarctic ozone hole appears in September to November, so look at that season there.",
            rising_words=("seeing a thicker ozone layer", "seeing a thinner ozone layer"),
            decimals=1,
        ),
        _v(
            id="sea_salinity",
            name="Sea surface salinity",
            theme="Ocean",
            dataset="smap_sss",
            units="psu",
            domain="ocean",
            agg="mean",
            fields=("sss_smap",),
            source_badge="SMAP",
            definition="How salty the top of the ocean is, in practical salinity units (about grams of salt per kilogram of seawater).",
            why_it_can_trend="Evaporation makes seawater saltier; rain, rivers and melting ice make it fresher. A stronger water cycle makes salty seas saltier and fresh seas fresher.",
            caveat="Measured from space only since 2015, so records are short; less reliable near coasts, near sea ice and in cold water.",
            rising_words=("getting saltier", "getting fresher"),
            decimals=2,
            # about ten whole years: too few yearly values to test, so the monthly view opens first
            default_mode="monthly",
        ),
        _v(
            id="chlorophyll",
            name="Ocean chlorophyll (phytoplankton)",
            theme="Ocean",
            dataset="modis_chl",
            units="mg/m³",
            domain="ocean",
            agg="mean",
            fields=("chlor_a",),
            source_badge="MODIS · Aqua",
            definition="The green pigment of the tiny plants (phytoplankton) floating near the ocean surface, in milligrams per cubic metre: a measure of ocean life.",
            why_it_can_trend="Warmer surface water mixes less and brings up fewer nutrients, which can mean fewer phytoplankton; rivers, upwelling and melting ice can feed more.",
            caveat="Clouds, sun glint and polar night leave gaps (years then use the months with data). Values differ a "
            "hundredfold between open ocean and coasts and averages are plain means, so a few blooming coastal areas can "
            "dominate a region's value and its trend. The Aqua satellite is ageing.",
            rising_words=("seeing more phytoplankton", "seeing less phytoplankton"),
            decimals=3,
        ),
    ]
}

PLANNED_VARIABLES: list[dict] = []  # everything in the design's catalog is now a variable

THEMES = [
    "Heat",
    "Water cycle",
    "Soil and land water",
    "Air quality",
    "Sky and air",
    "Fire",
    "Vegetation",
    "Ocean",
]


def get_variable(var_id: str) -> Variable:
    try:
        return VARIABLES[var_id]
    except KeyError:
        raise KeyError(f"unknown variable {var_id!r}") from None


def series_units(var: Variable, mode: str) -> str:
    """Units of the values the tests run on, e.g. mm/year for yearly rainfall totals."""
    if var.agg == "sum" and mode == "annual" and var.year_units:
        return var.year_units
    if var.agg == "sum" and mode == "season":
        return var.units.replace("/month", "/season")
    return var.units
