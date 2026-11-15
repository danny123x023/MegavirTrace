"""Detective cases: the catalogue is valid, and findings are written from numbers, not stories."""

from __future__ import annotations

import re

import pytest

from megavir.cases import BY_ID, CASES
from megavir.cases.catalog import Step
from megavir.cases.run import _highlight_text, label_text, ordinal, outlines
from megavir.catalog import THEMES, VARIABLES
from megavir.places.presets import PRESETS

PRESET_IDS = {f"preset:{p['id']}" for p in PRESETS}


def _regions(step: Step):
    return [r for r in (step.region, step.region_b) if r]


def test_catalogue_is_consistent():
    assert len(CASES) >= 16 and len(BY_ID) == len(CASES)  # ids are unique
    for c in CASES:
        assert re.fullmatch(r"[a-z0-9-]+", c.id), c.id
        assert c.theme in THEMES and c.kind in ("event", "change")
        assert c.story and c.question and c.takeaway and c.when and c.where
        assert 2 <= len(c.steps) <= 5 and 0 <= c.key < len(c.steps)
        for s in c.steps:
            assert s.kind in ("month", "trend", "compare"), (c.id, s.kind)
            assert s.variable in VARIABLES, (c.id, s.variable)
            assert s.title and s.look
            assert s.extreme in ("high", "low")
            assert (s.region_b is not None) == (s.kind == "compare"), (c.id, s.title)
            if s.kind == "month":
                assert s.year and 1 <= (s.month or 0) <= 12
            if s.mode == "season":
                assert s.season in ("DJF", "MAM", "JJA", "SON")
            for h in s.highlight:  # labels in the engine's form: 2003, 2003 JJA or 2022-04
                assert re.fullmatch(r"\d{4}( (DJF|MAM|JJA|SON))?|\d{4}-\d{2}", h), (c.id, h)
                if " " in h:
                    assert s.mode == "season" and h.endswith(s.season or "")
            for r in _regions(s):
                if "place" in r:
                    assert r["place"] in PRESET_IDS, (c.id, r)
                else:
                    w, so, e, n = r["bbox"]
                    assert -180 <= w < e <= 180 and -90 <= so < n <= 90
                    assert r["name"]["en"] and r["name"]["es"]


def test_stories_never_state_a_measured_result():
    """Stories and step hints say what happened and where to look; numbers come from the engine."""
    for c in CASES:
        for s in c.steps:
            assert "per decade" not in s.look and "standard deviation" not in s.look, (c.id, s.title)
        assert "per decade" not in c.story and "standard deviation" not in c.story, c.id


def test_every_region_is_outlined_once():
    c = BY_ID["lockdown-air-2020"]
    labels = [o["label"] for o in outlines(c)]
    assert labels == ["North China Plain", "Po Valley", "Delhi region", "US Northeast corridor"]
    assert outlines(BY_ID["pacific-northwest-heat-dome-2021"], "es")[0]["label"] == "el noroeste del Pacífico"


@pytest.mark.parametrize(
    ("label", "lang", "text"),
    [
        ("2003 JJA", "en", "2003 (Jun–Aug)"),
        ("2003 JJA", "es", "2003 (jun–ago)"),
        ("2022-04", "en", "April 2022"),
        ("2022-04", "es", "abril de 2022"),
        ("2016", "en", "2016"),
    ],
)
def test_label_text(label, lang, text):
    assert label_text(label, lang) == text


def test_ordinals():
    assert [ordinal(k, "en") for k in (1, 2, 3, 4, 11, 12, 13, 21, 22, 103)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "103rd",
    ]  # fmt: skip
    assert ordinal(3, "es") == "3.º"


def test_highlight_rank_and_later_records():
    labels = [str(y) for y in range(2000, 2010)]
    values = [1, 2, 9, 3, 4, 5, 10, 6, 11, None]
    step = Step("trend", "t", "l", "air_temp", {"place": "preset:globe"}, highlight=("2002",))
    text = _highlight_text(labels, values, step, "years", "en")
    assert text == "2002 is the 3rd highest of 9 years. Since then 2 were higher: 2006 and 2008."
    es = _highlight_text(labels, values, step, "años", "es")
    assert es == "2002 es el 3.º valor más alto de 9 años. Desde entonces, 2 han sido más altos: 2006 y 2008."
    # a dry record: the lowest end, and nothing lower since
    dry = Step("trend", "t", "l", "rainfall", {"place": "preset:globe"}, highlight=("2001",), extreme="low")
    assert _highlight_text(labels, values, dry, "years", "en").endswith("None since has been lower.")
    # several marked years: ranks only
    many = Step(
        "trend", "t", "l", "rainfall", {"place": "preset:globe"}, highlight=("2000", "2001"), extreme="low"
    )
    assert _highlight_text(labels, values, many, "years", "en") == (
        "2000 is the lowest of 9 years. 2001 is the 2nd lowest of 9 years."
    )


@pytest.mark.db
def test_case_endpoints(client):
    r = client.get("/cases", params={"lang": "en"})
    assert r.status_code == 200
    cases = r.json()["cases"]
    assert [c["id"] for c in cases] == [c.id for c in CASES]
    assert all(c["n_steps"] == len(BY_ID[c["id"]].steps) for c in cases)
    d = client.get("/cases/arctic-amplification", params={"lang": "es"}).json()
    assert d["lang"] == "es" and len(d["steps"]) == 3 and d["next"]["id"]
    for s in d["steps"]:  # each step has a finding from the engine, or says why not
        assert ("finding" in s) != ("error" in s)
        assert s["explore"]["v"] == "temp_change"
    assert client.get("/cases/not-a-case").status_code == 404


def test_a_year_still_under_way_is_named_as_such():
    from megavir.cases.run import partial_year_note

    assert partial_year_note(["2024", "2025", "2026"], "2026-10", "annual", "en") == ("2026", " (to October)")
    assert partial_year_note(["2024", "2025", "2026"], "2026-10", "annual", "es") == ("2026", " (hasta octubre)")
    assert partial_year_note(["2024", "2025"], "2025-12", "annual", "en") == (None, "")
    assert partial_year_note(["2025 JJA"], "2026-10", "season", "en") == (None, "")
