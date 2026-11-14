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
        fields=["T2M"],
        outputs={"air_temp": lambda f, m: k_to_c(f["T2M"])},
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


def gunzip(src: Path) -> Path:
    dest = src.with_suffix("")
    if not dest.exists():
        with gzip.open(src, "rb") as fi, open(dest, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    return dest
