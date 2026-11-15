"""Every endpoint on the small synthetic store (and the AI path with fake clients)."""

import json

import numpy as np
import pytest

from megavir.catalog import DATASETS, THEMES, VARIABLES
from tests.conftest import ORIGIN

pytestmark = pytest.mark.db


def test_health_and_catalog(client):
    assert client.get("/health").json()["ok"]
    cat = client.get("/variables").json()
    assert len(cat["variables"]) == len(VARIABLES) >= 31 and len(cat["themes"]) == len(THEMES) == 8
    assert all(v["data"] and v["data"]["kind"] == "synthetic" for v in cat["variables"])
    assert cat["planned"] == []
    ds = client.get("/datasets").json()
    assert len(ds["available"]) == len(DATASETS) >= 23


def test_place_search_and_outline(client):
    res = client.get("/places/search", params={"q": "testland"}).json()["results"]
    assert res[0]["id"] == "country:TST"
    res = client.get("/places/search", params={"q": "testvil"}).json()["results"]
    assert any(r["id"] == "city:1" for r in res)
    p = client.get("/places/country:TST").json()
    assert p["geometry"]["type"] == "Polygon"
    assert client.get("/places/nope:1").status_code == 404
    assert client.get("/places/presets").json()["count"] >= 120


def test_post_requires_allowed_origin(client):
    body = {"variable": "air_temp", "region": {"place": "country:TST"}}
    assert client.post("/analysis/trend", json=body).status_code == 403
    assert (
        client.post("/analysis/trend", json=body, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.post("/analysis/trend", json=body, headers=ORIGIN).status_code == 200


def test_trend_finds_the_planted_trend_and_is_cached(client):
    body = {"variable": "air_temp", "region": {"place": "admin1:TS-W"}, "cell_map": True}
    r1 = client.post("/analysis/trend", json=body, headers=ORIGIN).json()
    assert r1["data"]["kind"] == "synthetic"
    assert r1["verdict"]["caveats"][0].startswith("SYNTHETIC DATA")
    assert r1["stats"]["direction"] == "rising"
    assert r1["cell_map"]["n_cells"] > 10
    r2 = client.post("/analysis/trend", json=body, headers=ORIGIN).json()
    assert r2["id"] == r1["id"] and r2["compute_ms"] == r1["compute_ms"]  # served from the store
    rep = client.get(f"/reports/{r1['id']}").json()
    assert rep["id"] == r1["id"]


def test_all_modes_and_box(client):
    for mode, season in (("annual", None), ("season", "JJA"), ("monthly", None), ("raw", None)):
        body = {
            "variable": "rainfall",
            "region": {"bbox": [-96, 28, -91, 32]},
            "mode": mode,
            "season": season,
            "cell_map": False,
        }
        r = client.post("/analysis/trend", json=body, headers=ORIGIN)
        assert r.status_code == 200, r.text
        assert r.json()["series"]["mode"] == mode


def test_outside_data_area_is_a_clear_message(client):
    body = {"variable": "air_temp", "region": {"bbox": [10, 40, 12, 42]}}
    r = client.post("/analysis/trend", json=body, headers=ORIGIN)
    assert r.status_code == 422 and "synthetic" in r.json()["detail"]


def test_compare_and_opposites(client):
    body = {
        "variable": "air_temp",
        "region_a": {"place": "admin1:TS-W"},
        "region_b": {"place": "admin1:TS-E"},
    }
    c = client.post("/analysis/compare", json=body, headers=ORIGIN).json()
    d = c["comparison"]["difference"]
    assert d["slope_per_decade"] > 0  # the planted trend falls from west to east
    assert "minus" in c["verdict"]["sentences"][0]
    o = client.get("/analysis/opposites", params={"variable": "air_temp"}).json()
    assert "pairs" in o and o["mode"] == "annual" and "false-discovery" in o["note"]
    assert all(r["q"] <= 0.05 for r in o["rising"] + o["falling"])  # control across the regions tested
    gappy = client.get("/analysis/opposites", params={"variable": "land_water"}).json()
    assert gappy["mode"] == "monthly"  # each variable's own view, as in Explore


def test_scan_controls_false_discoveries(client):
    s = client.post("/analysis/scan", json={"region": {"place": "country:TST"}}, headers=ORIGIN).json()
    rows = [r for r in s["results"] if "q" in r]
    assert len(rows) == len(VARIABLES)
    assert all(r["q"] >= 0 for r in rows)


def test_month_detail(client):
    r = client.get(
        "/analysis/month", params={"variable": "air_temp", "year": 2010, "month": 7, "place": "country:TST"}
    )
    assert r.status_code == 200 and "z" in r.json()


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf", "ipynb", "json"])
def test_exports(client, fmt):
    r = client.post(
        "/analysis/trend",
        json={"variable": "ndvi", "region": {"place": "country:TST"}, "cell_map": False},
        headers=ORIGIN,
    ).json()
    e = client.get(f"/reports/{r['id']}/export", params={"format": fmt})
    assert e.status_code == 200 and len(e.content) > 200
    assert "attachment" in e.headers["content-disposition"]


def test_notebook_recomputes_the_result(client, tmp_path):
    import subprocess
    import sys

    import nbformat

    r = client.post(
        "/analysis/trend",
        json={"variable": "air_temp", "region": {"place": "country:TST"}, "cell_map": False},
        headers=ORIGIN,
    ).json()
    nb = nbformat.reads(
        client.get(f"/reports/{r['id']}/export", params={"format": "ipynb"}).text, as_version=4
    )
    script = tmp_path / "nb.py"
    script.write_text("\n\n".join(c.source for c in nb.cells if c.cell_type == "code"))
    out = subprocess.run(
        [sys.executable, "-I", str(script)], capture_output=True, text=True, cwd=tmp_path, timeout=120
    )
    assert "All numbers reproduced." in out.stdout, out.stdout + out.stderr


def test_open_data_api(client):
    r = client.get("/v1/trend", params={"variable": "air_temp", "place": "country:TST"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.json()["provenance"]["fingerprint"]


def test_rate_limit_answers_429(client, monkeypatch):
    from megavir.api import security

    lim = security.SlidingWindow(2, 60)
    assert lim.allow("x")[0] and lim.allow("x")[0] and not lim.allow("x")[0]


# --------------------------------------------------------------------------------------
# AI with fake clients
# --------------------------------------------------------------------------------------


@pytest.fixture
def fake_ai(monkeypatch, db):
    import megavir.ai as ai

    monkeypatch.setattr(ai, "_provider", lambda: "anthropic")
    monkeypatch.setattr(ai, "_model", lambda: "fake-model")
    ai._hourly = None
    return ai


def _fake_call(answer_fn):
    def call(messages, system, ctx):
        import megavir.ai as ai

        card = ai.run_tool(
            "run_trend_analysis", {"variable": "air_temp", "region": {"place": "country:TST"}}, ctx
        )
        return answer_fn(card), 100, 50

    return call


def test_ai_answer_with_checked_numbers(client, fake_ai, monkeypatch):
    def good(card):
        rate = card["per_decade"]["sen"]
        if card["significant"]:
            head, expl = f"Testland is warming by about {rate:.2f} °C per decade.", "Both tests agree."
        else:  # an honest answer for a trend the tests do not support
            head = f"Testland shows no clear trend; the best estimate is {rate:+.2f} °C per decade."
            expl = "The ups and downs could explain it."
        return {
            "headline": head,
            "explanation": expl + " The data are synthetic.",
            "analysis_ids": [card["analysis_id"]],
            "follow_up_questions": [],
        }

    monkeypatch.setattr(fake_ai, "_call", _fake_call(good))
    r = client.post("/ai/ask", json={"question": "Is Testland warming?"}, headers=ORIGIN).json()
    assert r["mode"] == "answered", r
    assert r["analyses"][0]["card"]["per_decade"]["sen"]  # card comes from the stored analysis


@pytest.mark.parametrize(
    "lang,template",
    [
        ("en", "Testland is warming by about 9.87 °C per decade."),
        ("es", "Testland se calienta unos 9,87 °C por década."),
        ("ar", "ترتفع الحرارة في Testland بنحو ٩٫٨٧ درجة لكل عقد."),
    ],
)
def test_ai_wrong_number_falls_back(client, fake_ai, monkeypatch, lang, template):
    monkeypatch.setattr(
        fake_ai,
        "_call",
        _fake_call(
            lambda card: {
                "headline": template,
                "explanation": "",
                "analysis_ids": [card["analysis_id"]],
                "follow_up_questions": [],
            }
        ),
    )
    r = client.post("/ai/ask", json={"question": "Is it warming?", "lang": lang}, headers=ORIGIN).json()
    assert r["mode"] == "fallback" and r["template_verdicts"]


def test_ai_reversed_direction_falls_back(client, fake_ai, monkeypatch):
    def reversed_(card):
        rate = card["per_decade"]["sen"]
        return {
            "headline": f"Testland is cooling by about {rate:.2f} °C per decade.",
            "explanation": "",
            "analysis_ids": [card["analysis_id"]],
            "follow_up_questions": [],
        }

    monkeypatch.setattr(fake_ai, "_call", _fake_call(reversed_))
    r = client.post("/ai/ask", json={"question": "Is it warming?"}, headers=ORIGIN).json()
    assert r["mode"] == "fallback"


def test_ai_service_failure_falls_back(client, fake_ai, monkeypatch):
    def boom(messages, system, ctx):
        raise fake_ai.ProviderError("timeout")

    monkeypatch.setattr(fake_ai, "_call", boom)
    r = client.post("/ai/ask", json={"question": "Is it warming?"}, headers=ORIGIN).json()
    assert r["mode"] == "fallback"


def test_ai_off_by_default(client):
    s = client.get("/ai/status").json()
    assert s["enabled"] is False
    r = client.post("/ai/ask", json={"question": "Is it warming?"}, headers=ORIGIN).json()
    assert r["mode"] == "unavailable"


def test_ai_daily_cap(client, fake_ai, monkeypatch):
    from megavir.config import settings

    monkeypatch.setattr(settings(), "ai_daily_cap", 0)
    r = client.post("/ai/ask", json={"question": "Is it warming?"}, headers=ORIGIN).json()
    assert r["mode"] == "unavailable" and "limit" in r["reason"]


def test_json_is_strict(client):
    r = client.post(
        "/analysis/trend", json={"variable": "sea_level", "region": {"place": "country:TST"}}, headers=ORIGIN
    )
    json.loads(r.text)  # no NaN or Infinity in the payload
    assert np.isfinite(r.json()["stats"]["per_decade"]["sen"])


def test_gappy_records_default_to_monthly(client):
    r = client.post(
        "/analysis/trend", json={"variable": "land_water", "region": {"place": "country:TST"}}, headers=ORIGIN
    )
    assert r.status_code == 200 and r.json()["series"]["mode"] == "monthly"
    r = client.post(
        "/analysis/trend", json={"variable": "air_temp", "region": {"place": "country:TST"}}, headers=ORIGIN
    )
    assert r.json()["series"]["mode"] == "annual"


def test_moves_together_endpoint(client):
    body = {
        "variable_a": "air_temp",
        "variable_b": "daily_high",
        "region": {"place": "country:TST"},
        "max_lag": 6,
    }
    r = client.post("/analysis/related", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = r.json()
    rel = d["relationship"]
    assert len(rel["lags"]) == 13 and rel["n_lags_tested"] == 13
    assert d["verdict"]["caveats"][0].startswith("SYNTHETIC DATA")
    assert any("not caused by" in c for c in d["verdict"]["caveats"])
    csv = client.get(f"/reports/{d['id']}/export", params={"format": "csv"})
    assert csv.status_code == 200 and b"lag_months" in csv.content
    assert client.get(f"/reports/{d['id']}/export", params={"format": "pdf"}).status_code == 422
    same = client.post("/analysis/related", json={**body, "variable_b": "air_temp"}, headers=ORIGIN)
    assert same.status_code == 422


def test_results_are_compressed_but_the_ai_progress_stream_is_not(client):
    """A big region's map is megabytes of JSON; the Ask page's progress lines must still arrive one by one."""
    gz = {**ORIGIN, "Accept-Encoding": "gzip"}
    body = {"variable": "air_temp", "region": {"place": "country:TST"}}
    r = client.post("/analysis/trend", json=body, headers=gz)
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip" and r.json()["verdict"]
    s = client.post("/ai/ask/stream", json={"question": "Is Testland warming?"}, headers=gz)
    assert s.status_code == 200 and "content-encoding" not in s.headers
