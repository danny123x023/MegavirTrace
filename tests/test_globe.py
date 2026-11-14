"""NASA GLOBE ground observations (FR14): aggregation rules, polling and the API, no network."""

import datetime as dt

import httpx
import numpy as np
import pytest

from megavir.context import globe
from tests.conftest import ORIGIN


def rec(site, date, hi=None, lo=None, mm=None, days=None, lat=30.0, lon=-95.0):
    data = {}
    if hi is not None:
        data.update({"airtempdailiesMaximumTemp": hi, "airtempdailiesMinimumTemp": lo})
    if mm is not None:
        data.update({"precipitationsLiquidAccumulation": mm, "precipitationsDaysAccumulated": days})
    return {
        "siteId": site,
        "siteName": f"S{site}",
        "latitude": lat,
        "longitude": lon,
        "measuredDate": date,
        "data": data,
    }


def test_air_temperature_needs_ten_days_per_site_month():
    recs = [rec(1, f"2020-01-{d:02d}", hi=20, lo=10) for d in range(1, 12)]  # 11 days -> kept
    recs += [rec(2, f"2020-01-{d:02d}", hi=30, lo=20) for d in range(1, 6)]  # 5 days -> dropped
    out = globe.monthly_series(recs, "air_mean")
    assert out["months"] == ["2020-01"] and out["values"] == [15.0] and out["n_sites"] == [1]


def test_regional_value_is_the_mean_over_sites():
    recs = [rec(1, f"2020-02-{d:02d}", hi=20, lo=10) for d in range(1, 15)]
    recs += [rec(2, f"2020-02-{d:02d}", hi=30, lo=20) for d in range(1, 15)]
    out = globe.monthly_series(recs, "air_max")
    assert out["values"] == [25.0] and out["n_sites"] == [2]


def test_precipitation_is_scaled_to_the_whole_month_and_needs_coverage():
    recs = [rec(1, f"2021-04-{d:02d}", mm=2.0, days=1) for d in range(1, 25)]  # 24 of 30 days covered
    out = globe.monthly_series(recs, "precip")
    assert out["values"][0] == pytest.approx(2.0 * 24 * 30 / 24)
    sparse = [rec(1, f"2021-05-{d:02d}", mm=5.0, days=1) for d in range(1, 10)]  # 9 days: dropped
    assert globe.monthly_series(sparse, "precip")["months"] == []


def test_bad_values_and_sites_outside_the_polygon_are_ignored():
    recs = [rec(1, f"2020-03-{d:02d}", hi=999, lo=10) for d in range(1, 15)]
    recs += [rec(2, f"2020-03-{d:02d}", hi=20, lo=10, lat=50) for d in range(1, 15)]
    out = globe.monthly_series(recs, "air_max", inside=lambda lat, lon: lat < 40)
    assert out["months"] == []


def test_anomaly_comparison_with_satellite():
    months = [f"{y}-{m:02d}" for y in range(2015, 2020) for m in range(1, 13)]
    rng = np.random.default_rng(1)
    signal = rng.normal(size=len(months))
    season = np.tile(np.sin(np.arange(12)), 5) * 10
    g = {"months": months, "values": list(season + signal + 3.0)}
    cmp = globe.compare_with_satellite(g, months, list(season * 0.5 + signal))
    assert cmp["n_shared"] == len(months)
    assert cmp["anomaly_correlation"] > 0.99  # seasonal cycles and offsets removed


def test_polling_waits_for_202_then_reads_200(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(202)
        return httpx.Response(200, json={"results": [rec(1, "2020-01-01", hi=1, lo=0)]})

    monkeypatch.setattr(globe.time, "sleep", lambda s: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = globe.fetch_observations(
        "air_temp_dailies", [-96, 29, -94, 31], dt.date(2020, 1, 1), dt.date(2020, 6, 30), client
    )
    assert len(out) == 1 and calls["n"] == 3


def test_polling_gives_up_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(globe.time, "sleep", lambda s: None)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(202)))
    with pytest.raises(globe.GlobeError, match="still preparing"):
        globe.fetch_observations(
            "air_temp_dailies", [0, 0, 1, 1], dt.date(2020, 1, 1), dt.date(2020, 1, 31), client
        )


@pytest.mark.db
def test_globe_endpoint_with_fake_fetch(client, monkeypatch):
    def fake_fetch(protocol, bbox, start, end, client=None):
        out = []
        for y in range(max(start.year, 2005), end.year + 1):
            for m in range(1, 13):
                out += [
                    rec(7, f"{y}-{m:02d}-{d:02d}", hi=25 + np.sin(m), lo=15, lat=30, lon=-95)
                    for d in range(1, 15)
                ]
        return out

    monkeypatch.setattr(globe, "fetch_observations", fake_fetch)
    r = client.post(
        "/analysis/trend",
        json={"variable": "air_temp", "region": {"place": "admin1:TS-W"}, "cell_map": False},
        headers=ORIGIN,
    ).json()
    g = client.get("/context/globe", params={"analysis_id": r["id"]})
    assert g.status_code == 200, g.text
    body = g.json()
    assert body["n_sites"] == 1 and body["comparison"]["n_shared"] > 12
    assert any("not used in the trend tests" in c for c in body["caveats"])


@pytest.mark.db
def test_globe_endpoint_rejects_unpaired_variables(client):
    r = client.post(
        "/analysis/trend",
        json={"variable": "ndvi", "region": {"place": "country:TST"}, "cell_map": False},
        headers=ORIGIN,
    ).json()
    g = client.get("/context/globe", params={"analysis_id": r["id"]})
    assert g.status_code == 422 and "No GLOBE protocol" in g.json()["detail"]
