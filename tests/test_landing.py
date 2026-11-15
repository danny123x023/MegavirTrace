"""The landing page's one request: what the site holds and one live result."""

from __future__ import annotations

import pytest

from megavir.api.service import LANDING_RECENT, LANDING_TREND


def test_landing_result_is_the_whole_earth_temperature_by_year():
    assert LANDING_TREND == {
        "variable": "temp_change",
        "region": {"place": "preset:globe"},
        "cell_map": False,
    }
    # the headline rate is the modern one: a straight line since 1880 would understate today's warming
    assert LANDING_RECENT == {**LANDING_TREND, "start_year": 1975}


@pytest.mark.db
def test_landing_summary(client):
    d = client.get("/landing").json()
    assert d["cases"] >= 1 and d["products"] == sorted(set(d["products"]))
    h = d["hero"]
    if d["variables"] == 0:  # only synthetic or test data here: no claims about the real Earth
        assert d["first_month"] is None and d["products"] == [] and h is None
        return
    assert d["first_month"] <= d["last_month"]
    if h is None:  # real temperature data not loaded in this database
        return
    assert len(h["labels"]) == len(h["values"]) == len(h["trend_line"]) >= 10
    assert "per decade" in h["headline"] and h["variable"]["id"] == "temp_change"
    assert h["since"] == 1975 and "1975" in h["headline"]
    first_line = next(i for i, v in enumerate(h["trend_line"]) if v is not None)
    assert h["labels"][first_line] >= "1975"  # the trend line covers the recent period only
    assert h["full_since"] <= int(h["labels"][0]) + 1 and h["full_per_decade"] is not None
    assert h["units"] and h["product"] and h["last_month"][:4] == h["labels"][-1]
    es = client.get("/landing", params={"lang": "es"}).json()["hero"]
    assert es["headline"] != h["headline"] and es["values"] == h["values"]  # same numbers, Spanish words
