"""Climate projections (FR15): ensemble summary, region limits and the background job, no network."""

import time

import pytest

from megavir.context import cmip6
from tests.conftest import ORIGIN


def fake_got(var="air_temp"):
    got = {}
    for k, m in enumerate(cmip6.MODELS):
        for y in cmip6.BASELINE_YEARS:
            got[(m, "historical", y)] = 20.0 + k  # each model has its own bias
        for sc, rate in (("ssp245", 0.02), ("ssp585", 0.04)):
            for y in cmip6.SAMPLE_YEARS:
                got[(m, sc, y)] = 20.0 + k + rate * (y - 2002.5) * (1 + 0.1 * k)
    return got


def test_changes_are_measured_from_each_models_own_baseline():
    obs = {
        "labels": ["1995", "2000", "2005", "2010", "2020"],
        "t": [1995.5, 2000.5, 2005.5, 2010.5, 2020.5],
        "values": [10, 10, 10, 10, 11],
        "mode": "annual",
    }
    r = cmip6.summarise(fake_got(), "air_temp", "°C", obs)
    s = r["scenarios"]["ssp585"]
    assert r["models_used"] == sorted(cmip6.MODELS)
    # model biases (20, 21, ...) cancel; changes grow with time and with the scenario
    assert s["median"][-1] == pytest.approx(0.04 * (2090 - 2002.5) * 1.2, rel=1e-6)
    assert r["scenarios"]["ssp245"]["median"][-1] < s["median"][-1]
    assert s["min"][-1] < s["median"][-1] < s["max"][-1] and s["models"] == [5, 5, 5, 5]
    assert r["observed"]["change"][-1] == pytest.approx(1.0)


def test_observed_line_only_for_yearly_values_and_from_its_own_baseline_years():
    # a summer series beside yearly model means would not be like for like
    season = {"labels": ["2001 JJA"], "t": [2001.58], "values": [1.0], "mode": "season"}
    obs, note = cmip6.observed_change(season, "air_temp")
    assert obs is None and "yearly" in note
    # IMERG starts in mid-2000: the baseline is the mean of 2001-2010, not two single years
    years = list(range(2001, 2026))
    rain = {"labels": [str(y) for y in years], "t": [y + 0.5 for y in years], "values": [1000.0] * 10 + [1100.0] * 15,
            "mode": "annual"}  # fmt: skip
    obs, note = cmip6.observed_change(rain, "rainfall")
    assert obs["baseline"] == [2001, 2010] and obs["change"][-1] == pytest.approx(10.0)  # percent
    short = {**rain, "labels": rain["labels"][8:], "t": rain["t"][8:], "values": rain["values"][8:]}
    assert cmip6.observed_change(short, "rainfall")[0] is None  # only 2009-2010 in the baseline period


def test_rainfall_changes_are_relative():
    obs = {"labels": [], "t": [], "values": [], "mode": "annual"}
    r = cmip6.summarise(fake_got(), "rainfall", "mm/year", obs)
    assert r["units"] == "%" and r["change_kind"] == "percent"


def test_region_limits():
    base = {
        "variable": {"id": "air_temp", "name": "Air temperature"},
        "region": {"id": None, "bbox": [-120, 20, -80, 50]},
    }
    with pytest.raises(cmip6.ProjectionError, match="up to"):
        cmip6.check_region(base)
    with pytest.raises(cmip6.ProjectionError, match="paired"):
        cmip6.check_region({**base, "variable": {"id": "ndvi", "name": "NDVI"}})


@pytest.mark.db
def test_projection_job_through_the_api(client, monkeypatch):
    def fake_value(client_, model, scenario, var, year, bbox):
        k = cmip6.MODELS.index(model)
        return 293.15 + k + (0 if scenario == "historical" else 0.03 * (year - 2002.5))

    monkeypatch.setattr(cmip6, "annual_region_value", fake_value)
    r = client.post(
        "/analysis/trend",
        json={"variable": "air_temp", "region": {"place": "admin1:TS-W"}, "cell_map": False},
        headers=ORIGIN,
    ).json()
    start = client.post("/context/projections", json={"analysis_id": r["id"]}, headers=ORIGIN)
    assert start.status_code == 200 and start.json()["total"] == 60
    for _ in range(100):
        st = client.get("/context/projections", params={"analysis_id": r["id"]}).json()
        if st["status"] != "running":
            break
        time.sleep(0.1)
    assert st["status"] == "done", st
    assert st["summary"][0].startswith("SSP2-4.5")
    assert st["result"]["scenarios"]["ssp245"]["median"][-1] == pytest.approx(
        0.03 * (2090 - 2002.5), rel=1e-6
    )
    assert any("not forecasts" in c for c in st["result"]["caveats"])
