"""The landing page's one request: what the site holds and one live result."""

from __future__ import annotations

import pytest

from megavir.api.service import LANDING_TREND


def test_landing_result_is_the_whole_earth_temperature_by_year():
    assert LANDING_TREND == {
        "variable": "temp_change",
        "region": {"place": "preset:globe"},
        "cell_map": False,
    }


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
    assert h["units"] and h["product"] and h["last_month"][:4] == h["labels"][-1]
    es = client.get("/landing", params={"lang": "es"}).json()["hero"]
    assert es["headline"] != h["headline"] and es["values"] == h["values"]  # same numbers, Spanish words
