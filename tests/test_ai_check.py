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
