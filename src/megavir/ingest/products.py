"""The 11 NASA data products: where they live, what to read and how to convert it.

Each product turns its files into monthly fields on its native grid, in standard orientation
(latitude south -> north, longitude -180 -> 180), in everyday units:

* mm per month instead of mm/hr or kg/m^2/s;  °C instead of K;
* NO2 in 10^15 molecules/cm^2;  sea level in mm;  fire carbon in g C/m^2/month.

Known traps handled here: IMERG is stored longitude-first; GLDAS starts at 60°S; MODIS CMG
and AIRS run north -> south; NASA-SSH and GRACE use 0..360 longitudes; fill values differ by
product.
"""

from __future__ import annotations

import datetime as dt
import gzip
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np

from .regrid import apply_fill, days_in_month, to_standard

KELVIN = 273.15


def month_abs_from_iso(s: str) -> int:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.year * 12 + d.month - 1


def regular(start: float, step: float, n: int) -> np.ndarray:
    return start + step * np.arange(n)


@dataclass
class Product:
    id: str  # dataset id in the catalog
    concept_id: str | None
    access: str  # "opendap" | "public"
    cadence: str  # "monthly" | "daily" | "weekly"
    target_res: float
    fields: list[str]
    outputs: dict  # variable id -> function(fields: dict[str, ndarray], month_abs) -> ndarray
    native_lats: np.ndarray | None = None  # file order
    native_lons: np.ndarray | None = None
    lon_first: bool = False
    fill: tuple = ()
    valid_range: tuple | None = None
    min_per_month: int = 1  # daily/weekly values a month needs, per cell
    coord_names: tuple = ("lat", "lon")
    public_urls: callable | None = None  # (mode, start_year, end_year) -> list[(url, filename)]
    notes: str = ""
    record_start: str = "2000-01"
    domain_mask: dict = field(default_factory=dict)  # var -> "land" | "ocean" (mask applied at ingest)
    multi_time: bool = False  # one granule holds many months (CERES EBAF)
    granule_filter: callable | None = None  # keep only some granules (monthly sea ice files)
    reader: callable | None = None  # access="download": (path, begin_iso) -> [(month, fields, lats, lons)]
    projected: bool = False  # lats/lons from the reader are 2-D (polar stereographic): bin, do not regrid


# --------------------------------------------------------------------------------------
# Unit conversions
# --------------------------------------------------------------------------------------


def _seconds(m: int) -> float:
    return 86400.0 * days_in_month(m)


def k_to_c(a):
    return a - KELVIN


PRODUCTS: dict[str, Product] = {}


def _reg(p: Product) -> Product:
    PRODUCTS[p.id] = p
    return p


_reg(
    Product(
        id="omi_no2",
        concept_id="C3333493715-GES_DISC",
        access="opendap",
        cadence="daily",
        target_res=0.5,
        fields=["ColumnAmountNO2TropCloudScreened"],
        outputs={"no2": lambda f, m: f["ColumnAmountNO2TropCloudScreened"] / 1e15},
        native_lats=regular(-89.875, 0.25, 720),
        native_lons=regular(-179.875, 0.25, 1440),
        fill=(-1.2676506e30,),
        valid_range=(-1e18, 1e18),
        min_per_month=3,
        record_start="2004-10",
        notes="Daily files; a month needs at least 3 days with data in a cell.",
    )
)

_reg(
    Product(
        id="gldas",
        concept_id="C1342986036-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["SoilMoi0_10cm_inst", "SoilMoi10_40cm_inst", "SoilMoi40_100cm_inst", "Evap_tavg"],
        outputs={
            "topsoil_moisture": lambda f, m: f["SoilMoi0_10cm_inst"],
            "soil_moisture": lambda f, m: (
                f["SoilMoi0_10cm_inst"] + f["SoilMoi10_40cm_inst"] + f["SoilMoi40_100cm_inst"]
            ),
            "evapotranspiration": lambda f, m: f["Evap_tavg"] * _seconds(m),  # kg/m2/s -> mm/month
        },
        native_lats=regular(-59.875, 0.25, 600),
        native_lons=regular(-179.875, 0.25, 1440),
        fill=(-9999.0,),
        record_start="2000-01",
        notes="Grid starts at 60°S.",
    )
)

_reg(
    Product(
        id="imerg",
        concept_id="C2723754851-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["precipitation"],
        outputs={"rainfall": lambda f, m: f["precipitation"] * 24.0 * days_in_month(m)},  # mm/hr -> mm/month
        native_lats=regular(-89.95, 0.1, 1800),
        native_lons=regular(-179.95, 0.1, 3600),
        lon_first=True,
        fill=(-9999.9,),
        valid_range=(0, 1000),
        record_start="2000-06",
        notes="Stored longitude-first (time, lon, lat).",
    )
)


def _micasa_urls(mode: str, y0: int, y1: int) -> list[tuple[str, str]]:
    base = "https://portal.nccs.nasa.gov/datashare/gmao/geos_carb/MiCASA/v1/netcdf/monthly"
    out = []
    for y in range(y0, y1 + 1):
        for mth in range(1, 13):
            name = f"MiCASA_v1_flux_x3600_y1800_monthly_{y}{mth:02d}.nc4"
            out.append((f"{base}/{y}/{name}", name))
    return out


_reg(
    Product(
        id="micasa",
        concept_id="C3273638632-GES_DISC",
        access="public",
        cadence="monthly",
        target_res=0.5,
        fields=["FIRE"],
        outputs={"fire_carbon": lambda f, m: f["FIRE"] * 1000.0 * _seconds(m)},  # kg C/m2/s -> g C/m2/month
        fill=(-9999.0, 1e15),
        valid_range=(0, 1),
        public_urls=_micasa_urls,
        record_start="2001-01",
        notes="Public copy at NASA NCCS; monthly files through the latest published year.",
    )
)


def _ndvi(f, m):
    a = f["CMG 0.05 Deg Monthly NDVI"]
    if np.nanmax(np.abs(a)) > 2:  # still raw integers (x 10000)
        a = a / 10000.0
    a[(a < -0.2) | (a > 1.0)] = np.nan
    return a


_reg(
    Product(
        id="modis_ndvi",
        concept_id="C2565788914-LPCLOUD",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["CMG 0.05 Deg Monthly NDVI"],
        outputs={"ndvi": _ndvi},
        native_lats=regular(89.975, -0.05, 3600),
        native_lons=regular(-179.975, 0.05, 7200),
        fill=(-3000.0,),
        record_start="2000-02",
        notes="HDF4 CMG grid, north -> south; read through OPeNDAP.",
    )
)

_reg(
    Product(
        id="nasa_ssh",
        concept_id="C3309442935-POCLOUD",
        access="opendap",
        cadence="weekly",
        target_res=0.5,
        fields=["ssha"],
        outputs={"sea_level": lambda f, m: f["ssha"] * 1000.0},  # m -> mm
        fill=(),
        valid_range=(-5, 5),
        min_per_month=2,
        coord_names=("latitude", "longitude"),
        # file order (checked against real granules): 0.5° cell centres, 0..360 longitudes
        native_lats=regular(-89.75, 0.5, 360),
        native_lons=regular(0.25, 0.5, 720),
        record_start="1992-11",
        notes="Weekly grids on 0..360 longitudes; a month needs at least 2 weeks per cell.",
    )
)

_reg(
    Product(
        id="merra2_stat",
        concept_id="C1276812828-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["T2MMAX", "T2MMIN", "TPRECMAX"],
        outputs={
            "daily_high": lambda f, m: k_to_c(f["T2MMAX"]),
            "nightly_low": lambda f, m: k_to_c(f["T2MMIN"]),
            "downpour": lambda f, m: f["TPRECMAX"] * 3600.0,  # kg/m2/s -> mm/hour
        },
        native_lats=regular(-90.0, 0.5, 361),
        native_lons=regular(-180.0, 0.625, 576),
        fill=(1e15,),
        record_start="1980-01",
    )
)


def _grace_urls(mode: str, y0: int, y1: int) -> list[tuple[str, str]]:
    # The file name carries the last month; resolved from the landing page at run time.
    return [("https://earth.gsfc.nasa.gov/geo/data/grace-mascons", "__resolve__")]


_reg(
    Product(
        id="grace",
        concept_id=None,
        access="public",
        cadence="monthly",
        target_res=0.5,
        fields=["lwe_thickness"],
        outputs={"land_water": lambda f, m: f["lwe_thickness"]},
        fill=(),
        valid_range=(-1e4, 1e4),
        public_urls=_grace_urls,
        record_start="2002-04",
        notes="One file with all months; mascons delivered on a 0.5° grid, 0..360 longitudes; months with gaps.",
    )
)

_reg(
    Product(
        id="merra2_slv",
        concept_id="C1276812859-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["T2M", "TO3", "TQV"],
        outputs={
            "air_temp": lambda f, m: k_to_c(f["T2M"]),
            "ozone": lambda f, m: f["TO3"],  # Dobson units
            "water_vapour": lambda f, m: f["TQV"],  # kg/m2 = mm of water if it all fell as rain
        },
        native_lats=regular(-90.0, 0.5, 361),
        native_lons=regular(-180.0, 0.625, 576),
        fill=(1e15,),
        record_start="1980-01",
    )
)


def _skin(f, m):
    a, d = f["SurfSkinTemp_A"], f["SurfSkinTemp_D"]
    return k_to_c((a + d) / 2.0)  # both passes needed, so day and night weigh the same


_reg(
    Product(
        id="airs",
        concept_id="C1701805662-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=1.0,
        fields=["SurfSkinTemp_A", "SurfSkinTemp_D"],
        outputs={"ground_temp": _skin, "sea_surface_temp": _skin},
        domain_mask={"ground_temp": "land", "sea_surface_temp": "ocean"},
        native_lats=regular(89.5, -1.0, 180),
        native_lons=regular(-179.5, 1.0, 360),
        fill=(-9999.0,),
        valid_range=(150, 400),
        record_start="2002-09",
        notes="HDF4, north -> south; ascending (day) and descending (night) passes averaged.",
    )
)


def _gistemp_urls(mode: str, y0: int, y1: int) -> list[tuple[str, str]]:
    return [
        (
            "https://data.giss.nasa.gov/pub/gistemp/gistemp1200_GHCNv4_ERSSTv5.nc.gz",
            "gistemp1200_GHCNv4_ERSSTv5.nc.gz",
        )
    ]


_reg(
    Product(
        id="gistemp",
        concept_id=None,
        access="public",
        cadence="monthly",
        target_res=2.0,
        fields=["tempanomaly"],
        outputs={"temp_change": lambda f, m: f["tempanomaly"]},
        fill=(32767,),
        valid_range=(-50, 50),
        public_urls=_gistemp_urls,
        record_start="1880-01",
        notes="2° grid kept; anomalies against 1951–1980.",
    )
)


# ---- FR2: six more variables -----------------------------------------------------------


def _lst(f, m):
    day, night = f["LST_Day_CMG"], f["LST_Night_CMG"]
    return k_to_c((day + night) / 2.0)  # both passes needed, so day and night weigh the same


_reg(
    Product(
        id="modis_lst",
        concept_id="C2565788897-LPCLOUD",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["LST_Day_CMG", "LST_Night_CMG"],  # names checked against NASA CMR (UMM-Var)
        outputs={"land_surface_temp": _lst},
        native_lats=regular(89.975, -0.05, 3600),
        native_lons=regular(-179.975, 0.05, 7200),
        fill=(0.0,),
        valid_range=(150, 400),
        record_start="2000-02",
        notes="HDF4 CMG grid, north -> south; stored integers x 0.02 = kelvin (applied from scale_factor).",
    )
)

_reg(
    Product(
        id="merra2_aer",
        concept_id="C1276812866-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["TOTEXTTAU"],  # total aerosol extinction optical thickness at 550 nm (checked in CMR)
        outputs={"aerosols": lambda f, m: f["TOTEXTTAU"]},
        native_lats=regular(-90.0, 0.5, 361),
        native_lons=regular(-180.0, 0.625, 576),
        fill=(1e15,),
        valid_range=(0, 10),
        record_start="1980-01",
    )
)

_reg(
    Product(
        id="oco2",
        concept_id="C2240248790-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["XCO2"],
        outputs={"co2": lambda f, m: f["XCO2"] * 1e6},  # mol/mol -> ppm
        native_lats=regular(-90.0, 0.5, 361),
        native_lons=regular(-180.0, 0.625, 576),
        fill=(1e15,),
        valid_range=(3e-4, 6e-4),
        record_start="2015-01",
        notes="GEOS assimilation of OCO-2 XCO2 on the MERRA-2 grid.",
    )
)

_reg(
    Product(
        id="ceres_ebaf",
        concept_id="C3880496704-LARC_CLOUD",
        access="opendap",
        cadence="monthly",
        target_res=1.0,
        fields=["toa_net_all_mon"],
        outputs={"energy_budget": lambda f, m: f["toa_net_all_mon"]},
        native_lats=regular(-89.5, 1.0, 180),
        native_lons=regular(0.5, 1.0, 360),
        fill=(-999.0,),
        valid_range=(-500, 500),
        record_start="2000-03",
        multi_time=True,
        notes="One granule holds the whole record (time, lat, lon); 0..360 longitudes.",
    )
)


def _seaice_monthly_only(g) -> bool:
    return bool(re.search(r"_(?:N|S)25km_\d{6}_v", g.name))


def _read_seaice(path: Path, begin: str):
    """NSIDC-0051 v2 monthly netCDF: x, y (metres, polar stereographic) and a <sensor>_ICECON field."""
    north = "_N25km_" in path.name
    with h5py.File(path, "r") as h5:
        ice = None

        def visit(name, obj):
            nonlocal ice
            if (
                ice is None
                and isinstance(obj, h5py.Dataset)
                and name.split("/")[-1].upper().endswith("_ICECON")
            ):
                ice = obj

        h5.visititems(visit)
        if ice is None:
            raise KeyError(f"no *_ICECON field in {path.name}")
        raw = np.asarray(ice[()], float)
        scale = _attr(ice, "scale_factor")
        x = np.asarray(_find_dataset(h5, "x")[()], float)
        y = np.asarray(_find_dataset(h5, "y")[()], float)
    raw = squeeze_to_2d(raw)
    if scale is not None and raw.max() > 1.5:
        conc = np.where(raw <= 250, raw * float(scale), np.nan)  # 251-255 are flags (pole hole, coast, land)
    elif raw.max() > 1.5:
        conc = np.where(raw <= 250, raw / 250.0, np.nan)
    else:
        conc = np.where((raw >= 0) & (raw <= 1.0), raw, np.nan)
    X, Y = np.meshgrid(x, y)
    from .regrid import polar_stereographic_to_latlon

    lat, lon = polar_stereographic_to_latlon(X, Y, north=north)
    m = _month_from_seaice_name(path.name)
    return [(m, {"ICECON": conc * 100.0}, lat, lon)]  # percent


def _month_from_seaice_name(name: str) -> int:
    mm = re.search(r"_(\d{4})(\d{2})_v", name)
    if not mm:
        raise ValueError(f"no YYYYMM in {name}")
    return int(mm.group(1)) * 12 + int(mm.group(2)) - 1


_reg(
    Product(
        id="nsidc_seaice",
        concept_id="C3177837840-NSIDC_CPRD",
        access="download",
        cadence="monthly",
        target_res=0.5,
        fields=["ICECON"],
        outputs={"sea_ice": lambda f, m: f["ICECON"]},
        record_start="1978-11",
        granule_filter=_seaice_monthly_only,
        reader=_read_seaice,
        projected=True,
        domain_mask={"sea_ice": "ocean"},
        notes="25 km polar stereographic (both hemispheres); monthly files only; binned to 0.5°.",
    )
)


def _read_snow(path: Path, begin: str):
    """MOD10CM v61 HDF4: Snow_Cover_Monthly_CMG, 0-100 %, values above 100 are flags."""
    from pyhdf.SD import SD, SDC

    sd = SD(str(path), SDC.READ)
    try:
        raw = np.asarray(sd.select("Snow_Cover_Monthly_CMG")[:], float)
    finally:
        sd.end()
    raw[raw > 100] = np.nan  # 107 lake ice, 111 night, 250 cloud, 253 not mapped, 254 water, 255 fill
    lats, lons = regular(89.975, -0.05, raw.shape[0]), regular(-179.975, 0.05, raw.shape[1])
    f, la, lo = to_standard(raw, lats, lons)
    return [(month_abs_from_iso(begin), {"Snow_Cover_Monthly_CMG": f}, la, lo)]


_reg(
    Product(
        id="modis_snow",
        concept_id="C3050353608-NSIDC_CPRD",
        access="download",
        cadence="monthly",
        target_res=0.5,
        fields=["Snow_Cover_Monthly_CMG"],
        outputs={"snow_cover": lambda f, m: f["Snow_Cover_Monthly_CMG"]},
        record_start="2000-03",
        reader=_read_snow,
        domain_mask={"snow_cover": "land"},
        notes="HDF4 CMG grid (no OPeNDAP): whole files are downloaded and read with pyhdf.",
    )
)


# --------------------------------------------------------------------------------------
# Added 2026-11-15 after a survey of NASA and partner archives: three more MERRA-2 collections,
# GPCP (rainfall since 1983), SMAP sea surface salinity and MODIS-Aqua ocean chlorophyll.
# Field names, grids, fill values and units were checked against a recent file of each.
# --------------------------------------------------------------------------------------

MERRA2_LATS, MERRA2_LONS = regular(-90.0, 0.5, 361), regular(-180.0, 0.625, 576)

_reg(
    Product(
        id="merra2_rad",
        concept_id="C1276812858-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["CLDTOT", "SWGDN"],
        outputs={
            "cloud_cover": lambda f, m: f["CLDTOT"] * 100.0,  # fraction -> %
            "sunshine": lambda f, m: f["SWGDN"],  # sunlight reaching the ground, W/m2
        },
        native_lats=MERRA2_LATS,
        native_lons=MERRA2_LONS,
        fill=(1e15,),
        record_start="1980-01",
    )
)

_reg(
    Product(
        id="merra2_lnd",
        concept_id="C1276812856-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["SNOMAS"],
        outputs={"snow_water": lambda f, m: f["SNOMAS"]},  # kg/m2 = mm of water in the snowpack
        domain_mask={"snow_water": "land"},
        native_lats=MERRA2_LATS,
        native_lons=MERRA2_LONS,
        fill=(1e15,),
        record_start="1980-01",
    )
)

_reg(
    Product(
        id="merra2_flx",
        concept_id="C1276812868-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["SPEED"],
        outputs={"wind_speed": lambda f, m: f["SPEED"]},  # m/s near the surface
        native_lats=MERRA2_LATS,
        native_lons=MERRA2_LONS,
        fill=(1e15,),
        valid_range=(0, 100),
        record_start="1980-01",
    )
)

_reg(
    Product(
        id="gpcp",
        concept_id="C3405935516-GES_DISC",
        access="opendap",
        cadence="monthly",
        target_res=0.5,
        fields=["sat_gauge_precip"],
        outputs={
            "rainfall_long": lambda f, m: f["sat_gauge_precip"] * days_in_month(m)
        },  # mm/day -> mm/month
        native_lats=regular(89.75, -0.5, 360),
        native_lons=regular(-179.75, 0.5, 720),
        fill=(-99999.0,),
        valid_range=(0, 100),
        record_start="1983-01",
        notes="0.5° grid stored north -> south; mm/day.",
    )
)

_reg(
    Product(
        id="smap_sss",
        concept_id="C2832226365-POCLOUD",
        access="opendap",
        cadence="monthly",
        target_res=0.25,
        fields=["sss_smap"],
        outputs={"sea_salinity": lambda f, m: f["sss_smap"]},  # practical salinity (psu)
        domain_mask={"sea_salinity": "ocean"},
        native_lats=regular(-89.875, 0.25, 720),
        native_lons=regular(0.125, 0.25, 1440),
        fill=(-9999.0,),
        valid_range=(0, 45),
        record_start="2015-04",
        notes="RSS V6, smoothed to about 70 km; 0..360 longitudes; no time dimension in the field.",
    )
)


def _chl_monthly(g) -> bool:
    # monthly 9 km files only; recent months are listed under two granule records for one file,
    # and the pipeline keeps one file per name
    return ".L3m.MO.CHL.chlor_a.9km.nc" in g.name and not g.name.endswith(".NRT.nc")


def _read_chl(path: Path, begin: str):
    """MODIS-Aqua L3 mapped chlorophyll, 9 km (2160 x 4320, north -> south), mg/m3."""
    with h5py.File(path, "r") as f:
        ds = f["chlor_a"]
        raw = np.asarray(ds[:], float)
        fill = float(np.asarray(ds.attrs.get("_FillValue", -32767.0)).ravel()[0])
        lats, lons = np.asarray(f["lat"][:], float), np.asarray(f["lon"][:], float)
    raw[(raw == fill) | (raw <= 0) | (raw > 100)] = np.nan
    fld, la, lo = to_standard(raw, lats, lons)
    return [(month_abs_from_iso(begin), {"chlor_a": fld}, la, lo)]


_reg(
    Product(
        id="modis_chl",
        concept_id="C3380709133-OB_CLOUD",
        access="download",
        cadence="monthly",
        target_res=0.5,  # 0.25° for 286 months needed over 5 GB of memory while storing (killed on a 17 GB server)
        fields=["chlor_a"],
        outputs={"chlorophyll": lambda f, m: f["chlor_a"]},
        domain_mask={"chlorophyll": "ocean"},
        record_start="2002-07",
        granule_filter=_chl_monthly,
        reader=_read_chl,
        notes="Whole monthly 9 km files (no OPeNDAP at OB.DAAC); read with h5py; averaged to 0.5°.",
    )
)


# --------------------------------------------------------------------------------------
# Reading files
# --------------------------------------------------------------------------------------


def _attr(ds, *names):
    for n in names:
        if n in ds.attrs:
            v = ds.attrs[n]
            if isinstance(v, bytes):
                v = v.decode()
            if isinstance(v, np.ndarray):
                v = v.ravel()[0] if v.size else None
            return v
    return None


def _find_dataset(h5: h5py.File, wanted: str):
    target = re.sub(r"[^0-9a-zA-Z]", "_", wanted).lower()
    hits = []

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            last = re.sub(r"[^0-9a-zA-Z]", "_", name.split("/")[-1]).lower()
            if last == target:
                hits.append(obj)

    h5.visititems(visit)
    if not hits:
        raise KeyError(f"{wanted} not found in {h5.filename}")
    return sorted(hits, key=lambda d: len(d.name))[0]


def read_h5_field(path: Path, wanted: str, product: Product) -> np.ndarray:
    """A field with fills removed and CF scale/offset applied (when stored packed)."""
    with h5py.File(path, "r") as h5:
        ds = _find_dataset(h5, wanted)
        raw = ds[()]
        fills = list(product.fill)
        for key in ("_FillValue", "missing_value", "MissingValue", "fill_value"):
            v = _attr(ds, key)
            if v is not None:
                fills.append(float(v))
        a = apply_fill(raw, fills)
        scale = _attr(ds, "scale_factor")
        offset = _attr(ds, "add_offset")
        # MODIS HDF4 attributes (scale 10000 meaning divide) are handled in the product function
        if (
            scale is not None
            and wanted != "CMG 0.05 Deg Monthly NDVI"
            and np.issubdtype(raw.dtype, np.integer)
        ):
            a = a * float(scale) + float(offset or 0.0)
        if product.valid_range:
            lo, hi = product.valid_range
            a[(a < lo) | (a > hi)] = np.nan
    return a


def read_coords(path: Path, names: tuple[str, str]) -> tuple[np.ndarray | None, np.ndarray | None]:
    with h5py.File(path, "r") as h5:
        out = []
        for cand in (names[0], names[1]):
            alts = {cand, "lat" if "lat" in cand else "lon", "latitude" if "lat" in cand else "longitude"}
            arr = None
            for a in alts:
                try:
                    arr = np.asarray(_find_dataset(h5, a)[()], float).ravel()
                    break
                except KeyError:
                    continue
            out.append(arr)
    return out[0], out[1]


def squeeze_to_2d(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a)
    while a.ndim > 2 and a.shape[0] == 1:
        a = a[0]
    if a.ndim != 2:
        raise ValueError(f"expected a 2-D field, got shape {a.shape}")
    return a


def standard_fields(path: Path, product: Product, lats: np.ndarray, lons: np.ndarray, lon_first: bool):
    """All of a product's fields from one file, in standard orientation."""
    out = {}
    std_lats = std_lons = None
    for name in product.fields:
        a = squeeze_to_2d(read_h5_field(path, name, product))
        f, std_lats, std_lons = to_standard(a, lats, lons, lon_first=lon_first)
        out[name] = f.astype(float)
    return out, std_lats, std_lons


def multi_time_fields(path: Path, product: Product, lats: np.ndarray, lons: np.ndarray, lon_first: bool):
    """[(time index, fields, lats, lons)] for a granule holding many months (time first)."""
    arrays = {name: np.asarray(read_h5_field(path, name, product)) for name in product.fields}
    nt = next(iter(arrays.values())).shape[0]
    out = []
    for k in range(nt):
        fields, la, lo = {}, lats, lons
        for name, a in arrays.items():
            f, la, lo = to_standard(a[k], lats, lons, lon_first=lon_first)
            fields[name] = f.astype(float)
        out.append((k, fields, la, lo))
    return out


def gunzip(src: Path) -> Path:
    dest = src.with_suffix("")
    if not dest.exists():
        with gzip.open(src, "rb") as fi, open(dest, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    return dest
