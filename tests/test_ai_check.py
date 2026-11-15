"""The AI number and direction check: numbers in many scripts, wrong numbers, reversed directions."""

import pytest

from megavir.ai.numbers import check_text, exempt, find_numbers, matches

ALLOWED = [0.31, 0.18, 0.44, 1880.0, 2025.0, 0.001, 23.0, 1234.5]


@pytest.mark.parametrize(
    "text,lang,expected",
    [
        ("about 0.31 °C per decade", "en", [0.31]),
        ("unos 0,31 °C por década", "es", [0.31]),
        ("1,234.5 mm", "en", [1234.5]),
        ("1.234,5 mm", "es", [1234.5]),
        ("٠٫٣١ درجة", "ar", [0.31]),  # Arabic-Indic digits, Arabic decimal separator
        ("۰٫۳۱ درجه", "fa", [0.31]),  # Persian digits
        ("०.३१ डिग्री", "hi", [0.31]),  # Devanagari digits
        ("12,34,567 लोग", "hi", [1234567.0]),  # Indian grouping
        ("０．３１℃", "ja", [0.31]),  # full-width digits and full stop
        ("0,31 °C", "fr", [0.31]),
        ("1 234,5 mm", "fr", [1234.5]),
    ],
)
def test_numbers_are_read_in_every_script(text, lang, expected):
    got = [n.value for n in find_numbers(text, lang)]
    assert got == pytest.approx(expected)


def test_small_whole_numbers_without_units_are_exempt():
    two_tests = find_numbers("Two tests (2 tests) agree", "en")[0]
    assert exempt(two_tests)
    two_degrees = find_numbers("2 °C per decade", "en")[0]
    assert not exempt(two_degrees)


def test_rounding_and_signs():
    n = find_numbers("0.3 °C", "en")[0]
    assert matches(n, [0.31])  # rounded to fewer digits
    n = find_numbers("+0.31", "en")[0]
    assert not matches(n, [-0.31])  # explicit sign must agree
    n = find_numbers("0.31", "en")[0]
    assert matches(n, [-0.31])  # magnitude only ("falling by 0.31")


@pytest.mark.parametrize(
    "lang,good,bad",
    [
        (
            "en",
            "Texas is warming by about 0.31 °C per decade since 1880.",
            "Texas is warming by about 0.52 °C per decade since 1880.",
        ),
        (
            "es",
            "Texas se calienta unos 0,31 °C por década desde 1880.",
            "Texas se calienta unos 0,52 °C por década desde 1880.",
        ),
        (
            "ar",
            "ترتفع الحرارة في تكساس بنحو ٠٫٣١ درجة لكل عقد منذ ١٨٨٠.",
            "ترتفع الحرارة في تكساس بنحو ٠٫٥٢ درجة لكل عقد منذ ١٨٨٠.",
        ),
        (
            "fa",
            "دما در تگزاس حدود ۰٫۳۱ درجه در هر دهه از ۱۸۸۰ افزایش یافته است.",
            "دما در تگزاس حدود ۰٫۵۲ درجه در هر دهه از ۱۸۸۰ افزایش یافته است.",
        ),
        (
            "hi",
            "टेक्सास में १८८० से हर दशक लगभग ०.३१ डिग्री गर्मी बढ़ी है।",
            "टेक्सास में १८८० से हर दशक लगभग ०.५२ डिग्री गर्मी बढ़ी है।",
        ),
        (
            "ja",
            "テキサスは1880年以来、10年あたり約０．３１℃上昇。",
            "テキサスは1880年以来、10年あたり約０．５２℃上昇。",
        ),
    ],
)
def test_a_wrong_number_fails_in_each_language(lang, good, bad):
    assert check_text(good, ALLOWED, [], lang).ok
    res = check_text(bad, ALLOWED, [], lang)
    assert not res.ok and res.unmatched


def test_reversed_direction_fails_even_with_right_numbers():
    d = [{"names": ["Texas"], "direction": "rising"}]
    assert check_text("Texas is warming by 0.31 °C per decade.", ALLOWED, d, "en").ok
    res = check_text("Texas is cooling by 0.31 °C per decade.", ALLOWED, d, "en")
    assert not res.ok and res.direction_errors
    res = check_text("Texas se está enfriando: 0,31 °C por década, a la baja.", ALLOWED, d, "es")
    assert not res.ok


def test_negated_direction_is_not_flagged():
    d = [{"names": ["Texas"], "direction": "rising"}]
    assert check_text("Texas is not cooling; it is warming by 0.31 °C per decade.", ALLOWED, d, "en").ok


# --- typed facts: the AI cannot pick a convenient number out of a long series -------------------


def _trend_result(sen=0.082, significant=True, direction="rising", region="the whole Earth"):
    import numpy as np

    years = list(range(1880, 2027))
    rng = np.random.default_rng(1)
    vals = [round(-0.3 + 0.0082 * (y - 1880) + float(rng.normal(0, 0.15)), 3) for y in years]
    return {
        "id": "abc",
        "kind": "trend",
        "region": {"name": region},
        "variable": {"name": "Surface temperature change", "i18n": {"es": {"name": "Cambio de temperatura"}}},
        "verdict": {
            "status": "significant" if significant else "not_significant",
            "headline": f"Surface temperature change in {region} has been rising since 1880: about {sen} °C per decade.",
            "sentences": ["Best estimate +0.082 °C per decade (95% range +0.075 to +0.089), 1880–2026."],
            "caveats": [],
            "shown": {"rate": str(sen), "lo": "+0.075", "hi": "+0.089", "p_mk": "< 0.001", "p_ols": "< 0.001"},
        },
        "stats": {
            "per_decade": {"sen": sen, "sen_low": 0.075, "sen_high": 0.089, "ols": 0.08, "ols_low": 0.07, "ols_high": 0.09},
            "mk": {"p": 1e-9, "tau": 0.7},
            "ols": {"p": 1e-9, "r1": 0.4, "n_eff": 60.0, "resid_sd": 0.15},
            "n": len(years),
            "years_needed": None if significant else 62.3,
            "years_more": None if significant else 40.0,
            "first": 1880.5,
            "last": 2026.5,
            "significant": significant,
            "direction": direction,
            "robustness": {"checks": [{"check": f"without {y}", "slope": 0.0082 + i * 1e-5} for i, y in enumerate(years)]},
            "acceleration": {"tested": False},
        },
        "series": {"labels": [str(y) for y in years], "values": vals, "plot_values": vals,
                   "tested": {"labels": [str(y) for y in years], "values": vals}},
    }  # fmt: skip


def _check(text, *results, lang="en"):
    from megavir.ai import _directions
    from megavir.ai.numbers import Facts, add_ratios, facts_from

    f = Facts()
    for r in results:
        f.extend(facts_from(r))
    add_ratios(f)
    return check_text(text, f, _directions({r["id"] + str(i): r for i, r in enumerate(results)}), lang)


def test_made_up_rates_fail_even_when_a_series_value_matches():
    r = _trend_result()
    assert _check("The whole Earth is warming by about 0.082 °C per decade.", r).ok
    for bad in ("0.5", "1.5", "3.0", "0.31", "0.21"):
        res = _check(f"The whole Earth is warming by {bad} °C per decade.", r)
        assert not res.ok and res.unmatched, bad


def test_a_year_value_is_allowed_only_next_to_its_year():
    r = _trend_result()
    v2016 = r["series"]["values"][2016 - 1880]
    v1950 = r["series"]["values"][1950 - 1880]
    assert _check(f"In 2016 the value was {v2016} °C.", r).ok
    assert not _check(f"In 2016 the value was {v1950} °C.", r).ok
    assert not _check("The record starts in 1850.", r).ok  # outside the record


def test_n_times_is_a_checked_ratio():
    arctic = _trend_result(sen=0.69, region="the Arctic (north of 66.5°N)")
    arctic["id"] = "arc"
    globe = _trend_result(sen=0.21)
    assert _check("The Arctic warms about 3 times as fast as the whole Earth.", arctic, globe).ok
    assert not _check("The Arctic warms about 5 times as fast as the whole Earth.", arctic, globe).ok


def test_directions_are_checked_with_negation_next_to_the_word():
    r = _trend_result()
    for bad in (
        "The whole Earth is getting colder by 0.082 °C per decade.",
        "The whole Earth has cooled by 0.082 °C per decade, which is not unusual.",
        "Temperatures on the whole Earth are not rising.",
    ):
        res = _check(bad, r)
        assert not res.ok and res.direction_errors, bad
    assert _check("The whole Earth is not cooling; it is warming by 0.082 °C per decade.", r).ok


def test_a_trend_the_tests_do_not_support_cannot_be_stated_as_fact():
    r = _trend_result(significant=False)
    res = _check("Rainfall in the whole Earth is rising.", r)
    assert not res.ok and "no clear trend" in res.direction_errors[0]
    assert not _check("The whole Earth shows a significant rise.", r).ok
    assert _check(
        "The whole Earth shows no clear trend; the best estimate is a rise of 0.082 °C per decade.", r
    ).ok
    assert _check("Telling it apart from the ups and downs would need about 40 more years of data.", r).ok


def test_spanish_reversed_directions_fail():
    r = _trend_result()
    res = _check("La temperatura en el whole Earth ha bajado 0,082 °C por década.", r, lang="es")
    assert not res.ok and res.direction_errors


def test_follow_up_questions_are_checked():
    from megavir.ai import verify

    r = _trend_result()
    good = {"headline": "The whole Earth is warming.", "explanation": "About 0.082 °C per decade since 1880.",
            "analysis_ids": ["abc"], "follow_up_questions": ["What does the 95% range tell you?"]}  # fmt: skip
    assert verify(good, {"abc": r}, "en")["ok"]
    bad = dict(good, follow_up_questions=["Why is it warming 1.5 °C per decade?"])
    out = verify(bad, {"abc": r}, "en")
    assert not out["ok"] and out["unmatched_numbers"]


def test_percent_quantities_use_percentage_points_and_never_percent_per_decade():
    """Sea ice in %: '2.9 percentage points per decade' is a checked rate; '2.9% per decade' is rejected,
    because it would mean a relative change the engine never computed."""
    r = _trend_result(sen=-2.9, direction="falling", region="the Arctic")
    r["stats"]["per_decade"].update(sen=-2.9, sen_low=-3.6, sen_high=-2.3)
    assert _check("The Arctic is falling by about 2.9 percentage points per decade.", r).ok
    assert _check("En el Ártico baja unos 2,9 puntos porcentuales por década.", r, lang="es").ok
    for bad in ("2.9% per decade", "2.9 % per decade", "2.9 %/decade"):
        res = _check(f"The Arctic is falling by about {bad}.", r)
        assert not res.ok and res.unmatched, bad
    # a made-up rate written in percentage points is still caught as a rate
    assert not _check("The Arctic is falling by about 4.7 percentage points per decade.", r).ok
