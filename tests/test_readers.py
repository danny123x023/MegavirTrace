"""Readers on fake files in each product's real layout: orientation, units and fill values.

Each fake file carries a known pattern (a value that depends on latitude and longitude), so
a flipped axis, a swapped longitude convention or a missed fill value shows up at once.
"""

import h5py
import numpy as np
import pytest

from megavir.ingest.products import PRODUCTS, month_abs_from_iso, standard_fields
from megavir.ingest.regrid import NativeGrid, Regridder, to_standard
from megavir.store import GridSpec


def pattern(lat, lon):
    """A smooth field that tells north from south and east from west."""
    return 280.0 + 0.2 * lat + 0.05 * lon


def write_h5(path, name, data, attrs=None, group=None):
    with h5py.File(path, "w") as f:
        g = f.require_group(group) if group else f
        ds = g.create_dataset(name, data=data)
        for k, v in (attrs or {}).items():
            ds.attrs[k] = v


def check_standard(field, lats, lons, expect_fn, tol=1e-3):
    assert lats[0] < lats[-1], "latitude must run south to north"
    assert lons[0] < lons[-1] and lons.min() >= -180 and lons.max() <= 180
    i, j = len(lats) // 3, len(lons) // 4
    assert field[i, j] == pytest.approx(expect_fn(lats[i], lons[j]), abs=tol)


def test_imerg_longitude_first(tmp_path):
    p = PRODUCTS["imerg"]
    lats, lons = p.native_lats[:40], p.native_lons[:60]
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    mmhr = (0.1 + 0.001 * (LA + 90) + 0.0001 * (LO + 180)).astype(np.float32)
    data = mmhr.T[None]  # (time, lon, lat)
    data[0, 5, 7] = -9999.9  # fill
    f = tmp_path / "3B-MO.MS.MRG.3IMERG.20240101.V07B.HDF5"
    write_h5(f, "precipitation", data, group="Grid")
    fields, la, lo = standard_fields(f, p, lats, lons, lon_first=True)
    out = p.outputs["rainfall"](fields, month_abs_from_iso("2024-01-01T00:00:00Z"))
    assert np.isnan(out[7, 5])
    assert out[3, 4] == pytest.approx(mmhr[3, 4] * 24 * 31, rel=1e-5)  # mm/hr -> mm per January


def test_gldas_starts_at_60s_and_converts_evaporation(tmp_path):
    p = PRODUCTS["gldas"]
    lats, lons = p.native_lats, p.native_lons[:50]
    assert lats[0] == pytest.approx(-59.875)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    with h5py.File(tmp_path / "GLDAS_NOAH025_M.A202401.021.nc4", "w") as fh:
        for name in p.fields:
            arr = np.full((1, *LA.shape), 10.0, np.float32)
            if name == "Evap_tavg":
                arr[:] = 2e-5
            arr[0, 0, 0] = -9999.0
            fh.create_dataset(name, data=arr)
    fields, la, lo = standard_fields(tmp_path / "GLDAS_NOAH025_M.A202401.021.nc4", p, lats, lons, False)
    m = month_abs_from_iso("2024-02-01T00:00:00Z")
    assert np.isnan(p.outputs["soil_moisture"](fields, m)[0, 0])
    assert p.outputs["soil_moisture"](fields, m)[5, 5] == pytest.approx(30.0)  # three layers summed
    assert p.outputs["evapotranspiration"](fields, m)[5, 5] == pytest.approx(
        2e-5 * 86400 * 29, rel=1e-5
    )  # leap February


def test_modis_cmg_north_to_south_and_raw_ndvi(tmp_path):
    p = PRODUCTS["modis_ndvi"]
    lats, lons = p.native_lats[:30], p.native_lons[:30]  # 89.975 downwards
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    raw = np.round(5000 + 10 * (LA - 88) + LO + 180).astype(np.int16)
    raw[2, 3] = -3000
    write_h5(tmp_path / "MOD13C2.nc4", "CMG_0_05_Deg_Monthly_NDVI", raw)
    fields, la, lo = standard_fields(tmp_path / "MOD13C2.nc4", p, lats, lons, False)
    nd = p.outputs["ndvi"](fields, 0)
    assert la[0] < la[-1]
    # after flipping, row 0 is the southernmost requested row (original last row)
    assert nd[0, 0] == pytest.approx(raw[-1, 0] / 10000.0)
    assert np.isnan(nd[-1 - 2, 3])


def test_merra2_kelvin_to_celsius_and_rate_to_mm_per_hour(tmp_path):
    p = PRODUCTS["merra2_stat"]
    lats, lons = p.native_lats, p.native_lons
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    with h5py.File(tmp_path / "MERRA2_400.statM_2d_slv_Nx.202401.nc4", "w") as fh:
        fh.create_dataset("T2MMAX", data=pattern(LA, LO)[None].astype(np.float32))
        fh.create_dataset("T2MMIN", data=(pattern(LA, LO) - 10)[None].astype(np.float32))
        tp = np.full((1, *LA.shape), 1e-4, np.float32)
        tp[0, 0, 0] = 1e15
        fh.create_dataset("TPRECMAX", data=tp)
    fields, la, lo = standard_fields(tmp_path / "MERRA2_400.statM_2d_slv_Nx.202401.nc4", p, lats, lons, False)
    hi = p.outputs["daily_high"](fields, 0)
    check_standard(hi, la, lo, lambda a, b: pattern(a, b) - 273.15)
    rate = p.outputs["downpour"](fields, 0)
    assert np.isnan(rate[0, 0]) and rate[3, 3] == pytest.approx(0.36)


def test_airs_north_to_south_fill_and_day_night_mean(tmp_path):
    p = PRODUCTS["airs"]
    lats, lons = p.native_lats, p.native_lons
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    with h5py.File(tmp_path / "AIRS.nc4", "w") as fh:
        a = pattern(LA, LO).astype(np.float32)
        d = (pattern(LA, LO) - 4).astype(np.float32)
        a[10, 10] = -9999.0
        fh.create_dataset("SurfSkinTemp_A", data=a)
        fh.create_dataset("SurfSkinTemp_D", data=d)
    fields, la, lo = standard_fields(tmp_path / "AIRS.nc4", p, lats, lons, False)
    t = p.outputs["ground_temp"](fields, 0)
    check_standard(t, la, lo, lambda a_, b_: pattern(a_, b_) - 2 - 273.15)
    assert np.isnan(t[len(la) - 1 - 10, 10])  # the fill, after the north-south flip


def test_ssh_0_to_360_longitudes_and_metres_to_mm():
    lats = np.arange(-79.75, 80, 0.5)
    lons = np.arange(0.25, 360, 0.5)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    field = 0.001 * np.where(LO > 180, LO - 360, LO)  # metres, depends on signed longitude
    f, la, lo = to_standard(field, lats, lons)
    assert lo[0] == pytest.approx(-179.75) and lo[-1] == pytest.approx(179.75)
    mm = PRODUCTS["nasa_ssh"].outputs["sea_level"]({"ssha": f}, 0)
    j = int(np.argmin(np.abs(lo - (-100.25))))
    assert mm[10, j] == pytest.approx(-100.25)


def test_conservative_regrid_keeps_global_mean():
    src_lats = np.arange(-89.95, 90, 0.1)[::5]  # coarse stand-in for 0.1 deg to keep the test fast
    src_lons = np.arange(-179.95, 180, 0.1)[::5]
    LA, LO = np.meshgrid(src_lats, src_lons, indexing="ij")
    field = np.cos(np.deg2rad(LA)) * 10 + np.sin(np.deg2rad(LO)) * 3
    dst = GridSpec.global_grid(2.0)
    out = Regridder(NativeGrid.from_centres(src_lats, src_lons), dst)(field)
    w_src = np.cos(np.deg2rad(LA))
    w_dst = np.cos(np.deg2rad(dst.lats))[:, None] * np.ones((1, dst.nx))
    assert np.nansum(out * w_dst) / w_dst.sum() == pytest.approx(
        (field * w_src).sum() / w_src.sum(), rel=2e-3
    )


def test_regrid_wraps_the_dateline_for_merra_grid():
    p = PRODUCTS["merra2_slv"]
    field = np.ones((p.native_lats.size, p.native_lons.size))
    out = Regridder(NativeGrid.from_centres(p.native_lats, p.native_lons), GridSpec.global_grid(0.5))(field)
    assert np.isfinite(out[:, -1]).all() and np.isfinite(out[:, 0]).all()  # no hole at +-180


def test_missing_data_needs_half_the_cell():
    lats = np.arange(-89.75, 90, 0.5)
    lons = np.arange(-179.75, 180, 0.5)
    field = np.ones((lats.size, lons.size))
    field[:, ::2] = np.nan  # half of every 1 deg cell missing in longitude
    field[:180:2, 1::2] = np.nan  # south: in every 2 x 2 block of half-degree cells, three are missing
    out = Regridder(NativeGrid.from_centres(lats, lons), GridSpec.global_grid(1.0))(field)
    assert np.isfinite(out[120]).all()  # north: 50 % valid -> kept
    assert np.isnan(out[30]).all()  # south: 25 % valid -> dropped
