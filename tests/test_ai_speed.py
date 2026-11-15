"""Fewer AI round trips: place names and variable ids in the tools, progress, stored region means."""

from __future__ import annotations

import json

import numpy as np
import pytest

from megavir import ai
from megavir.api import service
from megavir.catalog import VARIABLES
from tests.conftest import ORIGIN


def test_tools_list_the_variable_ids_and_take_place_names():
    run = next(t for t in ai.TOOLS if t["name"] == "run_trend_analysis")
    props = run["input_schema"]["properties"]
    assert props["variable"]["enum"] == list(VARIABLES)  # no list_variables round trip needed
    assert "place_name" in props["region"]["properties"]
    assert "place_name" in ai.SYSTEM and "at most 120 words" in ai.SYSTEM


@pytest.mark.db
def test_place_names_are_looked_up_by_the_tool(db):
    events: list[dict] = []
    ctx = {"lang": "en", "analyses": {}, "progress": events.append}
    out = ai.run_tool(
        "run_trend_analysis", {"variable": "air_temp", "region": {"place_name": "Testland"}}, ctx
    )
    assert out["places_used"] == ["Testland -> Testland (Test continent) [country:TST]"]
    assert len(ctx["analyses"]) == 1
    assert events == [
        {
            "step": "tool",
            "tool": "run_trend_analysis",
            "variable": "Air temperature (2 m)",
            "places": ["Testland"],
            "query": None,
        }
    ]
    missing = ai.run_tool(
        "run_trend_analysis", {"variable": "air_temp", "region": {"place_name": "Qwxzzy"}}, ctx
    )
    assert "no place called 'Qwxzzy'" in missing["error"]
    both = ai.run_tool(
        "compare_regions",
        {
            "variable": "air_temp",
            "region_a": {"place_name": "West Testshire"},
            "region_b": {"place": "admin1:TS-E"},
        },
        ctx,
    )
    assert len(both["places_used"]) == 1 and "error" not in both


@pytest.mark.db
def test_stored_region_mean_equals_a_fresh_one(db):
    reg = service.resolve_region(db, {"place": "country:TST"})
    fresh = service.regional_monthly(db, "air_temp", reg, need_cells=True)  # computes and stores
    stored = service.regional_monthly(db, "air_temp", reg)
    assert stored.cells is None  # came from the store
    assert np.array_equal(fresh.values, stored.values, equal_nan=True)
    assert np.array_equal(fresh.coverage, stored.coverage, equal_nan=True)


@pytest.mark.db
def test_ask_stream_sends_lines_then_the_result(client):
    r = client.post("/ai/ask/stream", json={"question": "Is Testland warming?"}, headers=ORIGIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    assert lines[-1]["type"] == "result"
    assert lines[-1]["result"]["mode"] == "unavailable"  # no AI service in the tests
    assert (
        client.post("/ai/ask/stream", json={"question": "Is Testland warming?"}).status_code == 403
    )  # Origin
