"""The AI number and direction check.

Every number the AI writes must match a number in the analyses it cites, within the rounding
it shows.  Numbers are read the way each language writes them, from Unicode CLDR data (via
Babel): the locale's decimal mark and grouping, in its Latin and native numbering systems.
Any Unicode decimal digit (Arabic-Indic, Persian, Devanagari, Bengali, full-width, ...) is
read as its value, and the full-width full stop and comma are understood.  Indian grouping
(12,34,567) is accepted.

Whole numbers 0-10 are exempt only when no unit follows them ("two tests", "3 reasons"),
so "2 °C per decade" is still checked.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

FULLWIDTH = {"．": ".", "，": ",", "－": "-", "−": "-", "–": "-", "％": "%", "٪": "%"}

UNIT_WORDS = (
    "°",
    "℃",
    "%",
    "‰",
    "mm",
    "cm",
    "m",
    "km",
    "g",
    "kg",
    "ppm",
    "ndvi",
    "molecules",
    "molec",
    "c ",
    "k ",
    "per",
    "por",
    "pour",
    "pro",
    "/",
    "×10",
    "x10",
    "deg",
    "grad",
    "grados",
    "degrees",
)


@lru_cache(maxsize=64)
def separators(lang: str) -> tuple[set[str], set[str]]:
    """Decimal marks and group separators for a language, Latin and native numbering systems."""
    decimals: set[str] = set()
    groups: set[str] = set()
    try:
        import babel.numbers as bn
        from babel import Locale

        loc = Locale.parse(lang)
        systems = {
            "latn",
            bn.get_default_numbering_system(lang) if hasattr(bn, "get_default_numbering_system") else "latn",
        }
        try:
            native = loc.other_numbering_systems.get("native")
            if native:
                systems.add(native)
        except Exception:  # noqa: BLE001
            pass
        for ns in systems:
            try:
                decimals.add(bn.get_decimal_symbol(lang, numbering_system=ns))
                groups.add(bn.get_group_symbol(lang, numbering_system=ns))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001 - unknown language: fall back to English
        decimals, groups = {"."}, {","}
    if groups & {" ", "\u00a0", "\u202f"}:  # people type a plain space where CLDR has a no-break one
        groups |= {" ", "\u00a0", "\u202f"}
    groups -= decimals
    return decimals or {"."}, groups


def normalise_text(text: str) -> str:
    out = []
    for ch in text:
        if ch in FULLWIDTH:
            out.append(FULLWIDTH[ch])
        elif unicodedata.category(ch) == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return "".join(out)


@dataclass
class FoundNumber:
    value: float
    decimals: int
    text: str
    start: int
    end: int
    has_unit: bool = False


def find_numbers(text: str, lang: str = "en") -> list[FoundNumber]:
    t = normalise_text(text)
    decs, groups = separators(lang)
    dec_cls = "".join(re.escape(d) for d in decs)
    grp_cls = "".join(re.escape(g) for g in groups)
    grp_part = rf"(?:[{grp_cls}]\d{{2,3}})*" if grp_cls else ""
    pat = re.compile(rf"(?<![A-Za-z0-9_.])([-+]?)(\d+{grp_part})(?:[{dec_cls}](\d+))?(?!\d)")
    out = []
    for m in pat.finditer(t):
        sign, whole, frac = m.group(1), m.group(2), m.group(3)
        # a group separator must be followed by valid groups (3 digits, or Indian 2-digit groups before the last 3)
        if grp_cls and any(g in whole for g in groups):
            parts = re.split(f"[{grp_cls}]", whole)
            if not (
                len(parts[-1]) == 3 and all(len(p) in (2, 3) for p in parts[1:-1]) and 1 <= len(parts[0]) <= 3
            ):
                continue
        digits = re.sub(f"[{grp_cls}]", "", whole) if grp_cls else whole
        try:
            v = float(digits + ("." + frac if frac else ""))
        except ValueError:
            continue
        if sign == "-":
            v = -v
        tail = t[m.end() : m.end() + 12].lower().lstrip()
        has_unit = any(tail.startswith(u) for u in UNIT_WORDS)
        out.append(FoundNumber(v, len(frac) if frac else 0, m.group(0), m.start(), m.end(), has_unit))
    return out


def matches(found: FoundNumber, allowed: list[float]) -> bool:
    """Same magnitude within the rounding shown (or 1-3 significant figures); an explicit
    sign must also agree.  Unsigned magnitudes are allowed ("falling by 0.3" for -0.3)."""
    signed = found.text.lstrip()[:1] in "+-"
    tol = 0.5 * 10 ** (-found.decimals) + 1e-12
    target = abs(found.value)
    for a in allowed:
        if a is None or not math.isfinite(a):
            continue
        if signed and a != 0 and (a > 0) != (found.value > 0):
            continue
        mag_a = abs(a)
        if abs(mag_a - target) <= tol:
            return True
        if mag_a > 0 and target > 0:
            m = math.floor(math.log10(mag_a))
            for sig in (1, 2, 3):
                if abs(round(mag_a, -m + sig - 1) - target) <= 1e-9 * max(1.0, target):
                    return True
    return False


def exempt(found: FoundNumber) -> bool:
    return found.decimals == 0 and 0 <= abs(found.value) <= 10 and not found.has_unit


# --------------------------------------------------------------------------------------
# Direction words
# --------------------------------------------------------------------------------------

UP = {
    "en": [
        "rising",
        "rose",
        "risen",
        "increasing",
        "increased",
        "warming",
        "warmed",
        "wetter",
        "greening",
        "growing",
        "upward",
        "gaining",
        "higher",
        "heavier",
        "more",
    ],
    "es": [
        "subiendo",
        "sube",
        "aumentando",
        "aumentó",
        "aumento",
        "calentando",
        "calentamiento",
        "más húmedo",
        "reverdecimiento",
        "creciente",
        "al alza",
    ],
}
DOWN = {
    "en": [
        "falling",
        "fell",
        "fallen",
        "decreasing",
        "decreased",
        "declining",
        "cooling",
        "cooled",
        "drier",
        "drying",
        "browning",
        "shrinking",
        "downward",
        "losing",
        "lower",
        "lighter",
        "less",
        "fewer",
    ],
    "es": [
        "bajando",
        "baja",
        "disminuyendo",
        "disminuyó",
        "descenso",
        "enfriando",
        "enfriamiento",
        "más seco",
        "secando",
        "a la baja",
    ],
}
NEGATIONS = {"en": ["not", "no ", "n't", "neither", "nor", "without"], "es": ["no ", "ni ", "sin "]}


@dataclass
class CheckResult:
    ok: bool
    unmatched: list[str] = field(default_factory=list)
    direction_errors: list[str] = field(default_factory=list)
    checked: int = 0


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


def check_text(text: str, allowed: list[float], directions: list[dict], lang: str = "en") -> CheckResult:
    """directions: [{"names": [place, variable words...], "direction": "rising"|"falling"|"flat"}]"""
    res = CheckResult(ok=True)
    for n in find_numbers(text, lang):
        if exempt(n):
            continue
        res.checked += 1
        if not matches(n, allowed):
            res.unmatched.append(n.text)
    up = UP.get(lang, UP["en"])
    down = DOWN.get(lang, DOWN["en"])
    neg = NEGATIONS.get(lang, NEGATIONS["en"])
    for sent in _sentences(text):
        low = sent.lower()
        if any(ng in low for ng in neg):
            continue
        for d in directions:
            if d["direction"] not in ("rising", "falling") or not any(
                nm.lower() in low for nm in d["names"] if nm
            ):
                continue
            wrong = down if d["direction"] == "rising" else up
            right = up if d["direction"] == "rising" else down
            hit_wrong = [w for w in wrong if re.search(rf"\b{re.escape(w)}\b", low)]
            hit_right = [w for w in right if re.search(rf"\b{re.escape(w)}\b", low)]
            if hit_wrong and not hit_right:
                res.direction_errors.append(f"{sent[:120]} (says {hit_wrong[0]}, data say {d['direction']})")
    res.ok = not res.unmatched and not res.direction_errors
    return res


def allowed_numbers(result: dict) -> list[float]:
    """Every number a stored analysis contains (statistics, shown strings, years, values)."""
    vals: list[float] = [95.0, 5.0, 0.05, 0.001, 10.0, 90.0]

    def walk(o):
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, int | float):
            if math.isfinite(float(o)):
                vals.append(float(o))
        elif isinstance(o, str):
            for n in find_numbers(o, "en"):
                vals.append(n.value)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in (
                    "geometry",
                    "lat",
                    "lon",
                    "frac",
                    "q",
                    "p",
                    "passes",
                    "slope_per_decade",
                ) and isinstance(v, list):
                    continue  # per-cell arrays are not quotable facts
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk({k: v for k, v in result.items() if k not in ("cell_map", "monthly")})
    if result.get("stats"):
        pd = result["stats"].get("per_decade", {})
        for k in ("sen", "sen_low", "sen_high", "ols", "ols_low", "ols_high"):
            if isinstance(pd.get(k), int | float):
                vals.append(pd[k] / 10.0)  # per year
    return vals
