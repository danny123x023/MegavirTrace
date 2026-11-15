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


# ---- FR2 products ---------------------------------------------------------------------------


def test_modis_lst_scaled_integers_day_night_mean(tmp_path):
    p = PRODUCTS["modis_lst"]
    lats, lons = p.native_lats[:20], p.native_lons[:30]
    day = np.full((20, 30), int(300 / 0.02), np.uint16)
    night = np.full((20, 30), int(290 / 0.02), np.uint16)
    night[4, 5] = 0  # fill
    with h5py.File(tmp_path / "MOD11C3.nc4", "w") as fh:
        for name, arr in (("LST_Day_CMG", day), ("LST_Night_CMG", night)):
            ds = fh.create_dataset(name, data=arr)
            ds.attrs["scale_factor"] = 0.02
            ds.attrs["_FillValue"] = np.uint16(0)
    fields, la, lo = standard_fields(tmp_path / "MOD11C3.nc4", p, lats, lons, False)
    t = p.outputs["land_surface_temp"](fields, 0)
    assert la[0] < la[-1]
    assert t[0, 0] == pytest.approx(295 - 273.15, abs=1e-3)
    assert np.isnan(t[20 - 1 - 4, 5])  # the fill, after the north-south flip


def test_oco2_xco2_to_ppm_and_merra_aerosols(tmp_path):
    for pid, field, value, var, expect in (
        ("oco2", "XCO2", 4.15e-4, "co2", 415.0),
        ("merra2_aer", "TOTEXTTAU", 0.18, "aerosols", 0.18),
    ):
        p = PRODUCTS[pid]
        arr = np.full((1, 361, 576), value, np.float32)
        arr[0, 0, 0] = 1e15
        write_h5(tmp_path / f"{pid}.nc4", field, arr)
        fields, la, lo = standard_fields(tmp_path / f"{pid}.nc4", p, p.native_lats, p.native_lons, False)
        out = p.outputs[var](fields, 0)
        assert np.isnan(out[0, 0]) and out[100, 100] == pytest.approx(expect, rel=1e-4)


def test_ceres_one_granule_many_months_and_0_360_longitudes(tmp_path):
    from megavir.ingest.products import multi_time_fields

    p = PRODUCTS["ceres_ebaf"]
    assert p.multi_time
    LA, LO = np.meshgrid(p.native_lats, p.native_lons, indexing="ij")
    data = np.stack([np.where(LO > 180, LO - 360, LO) + k for k in range(3)]).astype(
        np.float32
    )  # signed lon + month
    write_h5(tmp_path / "CERES_EBAF.nc4", "toa_net_all_mon", data)
    out = multi_time_fields(tmp_path / "CERES_EBAF.nc4", p, p.native_lats, p.native_lons, False)
    assert [k for k, *_ in out] == [0, 1, 2]
    k, fields, la, lo = out[2]
    assert lo[0] == pytest.approx(-179.5) and lo[-1] == pytest.approx(179.5)
    j = int(np.argmin(np.abs(lo - (-100.5))))
    assert fields["toa_net_all_mon"][50, j] == pytest.approx(-100.5 + 2)


def test_sea_ice_projection_flags_and_binning(tmp_path):
    from megavir.ingest.regrid import bin_to_grid, polar_stereographic_to_latlon

    # NSIDC's published corners of the 25 km grids
    lat, lon = polar_stereographic_to_latlon(-3850000, 5850000, north=True)
    assert lat == pytest.approx(30.98, abs=0.01) and lon == pytest.approx(168.35, abs=0.01)
    lat, lon = polar_stereographic_to_latlon(-3950000, 4350000, north=False)
    assert lat == pytest.approx(-39.23, abs=0.01) and lon == pytest.approx(-42.24, abs=0.01)

    p = PRODUCTS["nsidc_seaice"]
    x = np.arange(-3837500, 3750000, 25000.0)
    y = np.arange(5837500, -5350000, -25000.0)
    raw = np.full((1, y.size, x.size), 200, np.uint8)  # 200 * 0.004 = 0.8 -> 80 %
    raw[0, :5, :] = 254  # land flag
    f = tmp_path / "NSIDC0051_SEAICE_PS_N25km_202401_v2.0.nc"
    with h5py.File(f, "w") as fh:
        ds = fh.create_dataset("F17_ICECON", data=raw)
        ds.attrs["scale_factor"] = 0.004
        fh.create_dataset("x", data=x)
        fh.create_dataset("y", data=y)
    ((month, fields, la, lo),) = p.reader(f, "2024-01-01T00:00:00Z")
    assert month == 2024 * 12 and la.shape == (y.size, x.size)
    conc = p.outputs["sea_ice"](fields, month)
    assert np.nanmax(conc) == pytest.approx(80.0) and np.isnan(conc[0, 0])
    spec = GridSpec.global_grid(0.5)
    grid = bin_to_grid(la, lo, conc, spec)
    assert np.nanmean(grid) == pytest.approx(80.0) and np.isnan(grid[0]).all()  # nothing near the South Pole
    # near the pole a 0.5° cell is narrower than a 25 km pixel: no cell may be left empty
    assert np.isfinite(grid[spec.lats >= 75.0]).all()

    # the pole hole (flag 251) is ice, as in NSIDC's Sea Ice Index
    rr = np.hypot(*np.meshgrid(x, y))
    raw[0][rr < 300000] = 251
    with h5py.File(f, "w") as fh:
        ds = fh.create_dataset("F17_ICECON", data=raw)
        ds.attrs["scale_factor"] = 0.004
        fh.create_dataset("x", data=x)
        fh.create_dataset("y", data=y)
    ((_, fields, la, lo),) = p.reader(f, "2024-01-01T00:00:00Z")
    conc = p.outputs["sea_ice"](fields, month)
    assert np.nanmax(conc) == pytest.approx(100.0) and conc[rr < 300000].min() == pytest.approx(100.0)
    polar = bin_to_grid(la, lo, conc, spec)
    assert np.nanmean(polar[spec.lats > 88.0]) == pytest.approx(100.0)
    assert p.granule_filter(type("G", (), {"name": "NSIDC0051_SEAICE_PS_N25km_202401_v2.0.nc"})())
    assert not p.granule_filter(type("G", (), {"name": "NSIDC0051_SEAICE_PS_N25km_20240131_v2.0.nc"})())


def test_modis_snow_hdf4_flags(tmp_path):
    from pyhdf.SD import SD, SDC

    p = PRODUCTS["modis_snow"]
    f = tmp_path / "MOD10CM.A2024001.061.hdf"
    sd = SD(str(f), SDC.WRITE | SDC.CREATE)
    arr = np.full((36, 72), 40, np.uint8)
    arr[0, :] = 250  # cloud flag in the northernmost row
    ds = sd.create("Snow_Cover_Monthly_CMG", SDC.UINT8, arr.shape)
    ds[:] = arr
    ds.endaccess()
    sd.end()
    ((month, fields, la, lo),) = p.reader(f, "2024-01-01T00:00:00Z")
    snow = p.outputs["snow_cover"](fields, month)
    assert month == 2024 * 12 and la[0] < la[-1]
    assert np.isnan(snow[-1]).all() and snow[0, 0] == 40.0


def test_streaming_accumulator_means_and_memory_shape():
    from megavir.ingest.pipeline import MonthlyAccumulator

    spec = GridSpec.global_grid(2.0)
    acc = MonthlyAccumulator(spec, min_count=3)
    f = np.ones((spec.ny, spec.nx))
    for month in (100, 101, 102):  # three "days" per month, in time order
        for k in range(3):
            acc.add(month, f * (month + k))
    assert len(acc.open) <= MonthlyAccumulator.KEEP_OPEN  # finished months were closed as data moved on
    acc.add(100, f * 1000)  # a late value reopens month 100
    m0, cube = acc.cube()
    assert m0 == 100 and cube.shape == (3, spec.ny, spec.nx) and cube.dtype == np.float32
    assert cube[1, 0, 0] == pytest.approx(102.0)
    assert cube[0, 0, 0] == pytest.approx((100 + 101 + 102 + 1000) / 4)


def test_months_with_too_few_values_are_missing():
    from megavir.ingest.pipeline import MonthlyAccumulator

    spec = GridSpec.global_grid(2.0)
    acc = MonthlyAccumulator(spec, min_count=3)
    acc.add(5, np.ones((spec.ny, spec.nx)))
    _, cube = acc.cube()
    assert np.isnan(cube).all()


def test_sea_surface_temperature_drops_frozen_sea(monkeypatch):
    """AIRS skin temperature over sea ice is the ice's temperature: those cell-months are dropped."""
    from types import SimpleNamespace

    import megavir.store as store
    from megavir.ingest.pipeline import drop_sea_ice

    ice_spec = GridSpec.global_grid(0.5)
    sst_spec = GridSpec.global_grid(1.0)
    m0 = 2020 * 12  # Jan 2020
    ice = np.zeros((3, ice_spec.ny, ice_spec.nx), np.float32)
    ice[0, 340:, :] = 80.0  # January: ice north of 80°N
    ice[1, 340:, :4] = 20.0  # February: one 0.5° cell of a 1° block above the 15 % edge
    ice[2] = np.nan  # March: no ice data
    fake = SimpleNamespace(id=7, kind="real", spec=ice_spec, month0=m0, n_months=3)
    monkeypatch.setattr(store, "active_versions", lambda conn: {"sea_ice": fake})
    monkeypatch.setattr(store, "read_full", lambda conn, v: ice.copy())

    cube = np.full((4, sst_spec.ny, sst_spec.nx), 5.0, np.float32)
    cube[0, 0, 0] = -40.0  # colder than any liquid sea
    note = drop_sea_ice(None, cube, sst_spec, m0, -2.0)
    assert np.isnan(cube[0, 0, 0])
    assert np.isnan(cube[0, 170:, :]).all() and np.isfinite(cube[0, :170, 1:]).all()
    assert np.isnan(cube[1, 170:, :2]).all() and np.isfinite(cube[1, 170:, 2:]).all()  # block maximum
    # March and April lie outside the ice record: the same calendar month of earlier years is used,
    # and there is none here, so nothing is dropped by ice
    assert np.isfinite(cube[2]).all() and np.isfinite(cube[3]).all()
    assert "sea ice" in note and "beyond the ice record" in note


def test_every_stored_grid_has_a_land_mask_resolution():
    """SMAP salinity is stored at 0.25°: without a 0.25° mask its sea-only weighting was skipped."""
    from megavir.ingest.products import PRODUCTS
    from megavir.places.load import mask_resolutions

    assert {float(p.target_res) for p in PRODUCTS.values()} <= set(mask_resolutions())
    assert 0.25 in mask_resolutions()


def test_a_missing_land_mask_is_resampled_from_a_stored_one():
    from megavir.store import read_land_mask

    lf = np.zeros((360, 720), np.float32)
    lf[200, 300] = 1.0

    class Conn:
        def execute(self, sql, params=None):
            class R:
                def fetchone(self_inner):
                    if params and params[1] == 0.5:
                        from megavir.store import encode_array

                        return {"data": encode_array(lf)}
                    return None

                def __iter__(self_inner):
                    return iter([{"res_deg": 0.5}])

            return R()

    import megavir.store as store

    store._mask_cache.clear()
    g, fine = read_land_mask(Conn(), 0.25)
    assert g.res == 0.25 and fine.shape == (720, 1440)
    assert fine[400:402, 600:602].min() == 1.0 and fine.sum() == 4.0  # one 0.5° cell = 2 x 2 cells of 0.25°
    store._mask_cache.clear()
    g2, coarse = read_land_mask(Conn(), 1.0)
    assert coarse.shape == (180, 360) and coarse[100, 150] == pytest.approx(0.25)
    store._mask_cache.clear()


def test_unfinished_months_are_not_stored_and_weekly_grids_are_dated_by_their_centre():
    from megavir.ingest.pipeline import _midpoint, _months_from_bounds, last_complete_month

    omi = PRODUCTS["omi_no2"]
    files = [("2026-11-12T00:00:00Z", None, {"end": "2026-11-12T23:59:59Z"})]
    assert last_complete_month(omi, files) == 2026 * 12 + 9  # October: November is still under way
    files = [("2026-10-31T00:00:00Z", None, {"end": "2026-10-31T23:59:59Z"})]
    assert last_complete_month(omi, files) == 2026 * 12 + 9
    assert last_complete_month(PRODUCTS["merra2_slv"], files) is None  # monthly files: no cut
    # a NASA-SSH grid for 28 Oct - 7 Nov 1992 is centred on 2 November
    assert month_abs_from_iso(_midpoint("1992-10-28T00:00:00Z", "1992-11-07T00:00:00Z")) == 1992 * 12 + 10
    # GRACE-FO: 22 Oct - 9 Nov 2018 has most of its days in October; 10-30 Nov is November
    b = np.array([["2018-10-22", "2018-11-09"], ["2018-11-10", "2018-11-30"]], dtype="datetime64[D]")
    assert _months_from_bounds(b) == [2018 * 12 + 9, 2018 * 12 + 10]
