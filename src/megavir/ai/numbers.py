"""The AI number and direction check.

Every number the AI writes must match a number of the right kind in the analyses it cites,
within the rounding it shows:

* a rate ("0.21 °C per decade") must be one of the rates shown (Sen's slope, least squares,
  their 95 % ranges, the pace before and after a change, a comparison's difference);
* a p-value must be one of the p-values;
* a year must lie inside a cited record (or be a projection year);
* "N times" must be the ratio of two cited rates;
* any other number must be a headline statistic or a number shown in a verdict, or the
  value of a year or month named in the same sentence ("in 2016 it was 1.0 °C").

So the AI cannot pick a convenient number out of a long series.  Numbers are read the way each
language writes them, from Unicode CLDR data (via Babel): the locale's decimal mark and
grouping, in its Latin and native numbering systems.  Any Unicode decimal digit
(Arabic-Indic, Persian, Devanagari, Bengali, full-width, ...) is read as its value, and the
full-width full stop and comma are understood.  Indian grouping (12,34,567) is accepted.

Whole numbers 0-10 are exempt only when no unit follows them ("two tests", "3 reasons"),
so "2 °C per decade" and "3 times faster" are still checked.

The direction check reads every sentence about a cited trend: a reversed direction, a
direction stated as fact when the tests found no clear trend, and "not rising" for a
significant rise all fail.  A negation only counts when it is next to the word it negates.
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


RATIO_WORDS = ("times", "time ", "×", "x ", "-fold", " fold", "veces", "vez ", "fois", "mal ")


def _is_ratio(text: str, found: FoundNumber) -> bool:
    tail = normalise_text(text)[found.end : found.end + 8].lower()
    return any(tail.lstrip().startswith(w.strip()) or tail.startswith(w) for w in RATIO_WORDS)


def exempt(found: FoundNumber, text: str = "") -> bool:
    if text and _is_ratio(text, found):
        return False
    return found.decimals == 0 and 0 <= abs(found.value) <= 10 and not found.has_unit


# --------------------------------------------------------------------------------------
# What the cited analyses let the AI say
# --------------------------------------------------------------------------------------

FIXED = [95.0, 5.0, 0.05, 0.001, 0.025, 50.0, 90.0, 80.0]  # 95 % ranges, the 5 % level, 50 % coverage
MONTHS = {
    "en": ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
}  # fmt: skip


@dataclass
class Facts:
    general: list[float] = field(default_factory=list)  # headline statistics, numbers shown in verdicts
    rates: list[float] = field(default_factory=list)  # per decade
    pvalues: list[float] = field(default_factory=list)
    years: set[int] = field(default_factory=set)
    ratios: list[float] = field(default_factory=list)
    values: dict[str, list[float]] = field(default_factory=dict)  # "2016" or "2016-07" -> values
    central: list[float] = field(default_factory=list)  # best-estimate rates, for "N times as fast"

    @classmethod
    def plain(cls, allowed: list[float]) -> Facts:
        """Every number allowed everywhere (older callers and tests)."""
        yrs = {int(a) for a in allowed if a is not None and float(a).is_integer() and 1000 <= a <= 2200}
        return cls(list(allowed), list(allowed), list(allowed), yrs, list(allowed), {}, list(allowed))

    def extend(self, other: Facts) -> None:
        self.general += other.general
        self.rates += other.rates
        self.pvalues += other.pvalues
        self.years |= other.years
        self.ratios += other.ratios
        self.central += other.central
        for k, v in other.values.items():
            self.values.setdefault(k, []).extend(v)


def _nums(o) -> list[float]:
    """Numbers in a value: itself, the numbers written in a string, or those of a list."""
    if isinstance(o, bool) or o is None:
        return []
    if isinstance(o, int | float):
        return [float(o)] if math.isfinite(float(o)) else []
    if isinstance(o, str):
        return [n.value for n in find_numbers(o, "en")]
    if isinstance(o, list | tuple):
        return [x for v in o for x in _nums(v)]
    if isinstance(o, dict):
        return [x for v in o.values() for x in _nums(v)]
    return []


def _verdict_numbers(v: dict | None) -> list[float]:
    if not v:
        return []
    out = _nums(v.get("shown", {}))
    for k in ("headline", "sentences", "caveats"):
        out += _nums(v.get(k))
    return out


def _stats_facts(st: dict, f: Facts) -> None:
    pd = st.get("per_decade") or {}
    f.rates += _nums([pd.get(k) for k in ("sen", "sen_low", "sen_high", "ols", "ols_low", "ols_high")])
    f.central += _nums([pd.get(k) for k in ("sen", "ols")])
    for k in ("mk", "ols"):
        f.pvalues += _nums((st.get(k) or {}).get("p"))
    ols = st.get("ols") or {}
    f.general += _nums([st.get("n"), st.get("years_needed"), st.get("years_more"), st.get("effect_ratio")])
    f.general += _nums([ols.get("r1"), ols.get("n_eff"), ols.get("resid_sd"), (st.get("mk") or {}).get("tau")])
    acc = st.get("acceleration") or {}
    if acc.get("tested"):
        f.rates += [10 * x for x in _nums([acc.get("slope_early"), acc.get("slope_late")])]
        f.pvalues += _nums(acc.get("p"))
        f.years |= {int(x) for x in _nums(acc.get("split"))}
    tp = st.get("turning") or {}
    if tp.get("preferred"):
        f.rates += [10 * x for x in _nums([tp.get("slope_before"), tp.get("slope_after")])]
    rob = st.get("robustness") or {}
    for c in rob.get("checks") or []:
        if c.get("check") in ("first half", "second half", "without first and last years"):
            f.rates += [10 * x for x in _nums(c.get("slope"))]
    for u in st.get("unusual") or []:
        f.general += _nums([u.get("departure"), u.get("sd_units")])
    for k in ("first", "last"):
        if isinstance(st.get(k), int | float):
            f.years.add(int(math.floor(st[k])))


def _record_years(f: Facts, labels: list) -> None:
    yrs = sorted({int(str(lab)[:4]) for lab in labels or [] if str(lab)[:4].isdigit()})
    if yrs:
        f.years |= set(range(yrs[0] - 1, yrs[-1] + 2))


def _label_key(lab) -> str:
    lab = str(lab)
    if re.match(r"^\d{4}-\d{2}", lab):
        return lab[:7]  # a month
    return lab[:4]  # a year (or a season of that year)


def _label_values(f: Facts, labels: list, values: list) -> None:
    for lab, v in zip(labels or [], values or [], strict=False):
        if isinstance(v, int | float) and math.isfinite(v):
            f.values.setdefault(_label_key(lab), []).append(float(v))


def _with_per_decade(st: dict) -> dict:
    """A comparison's per-region statistics carry slopes per year; add the per-decade view."""
    if st.get("per_decade"):
        return st
    sen, ols = st.get("sen") or {}, st.get("ols") or {}

    def dec(x):
        return 10 * x if isinstance(x, int | float) else None

    return {**st, "per_decade": {"sen": dec(sen.get("slope")), "sen_low": dec(sen.get("ci_low")),
                                 "sen_high": dec(sen.get("ci_high")), "ols": dec(ols.get("slope"))}}  # fmt: skip


def facts_from(result: dict) -> Facts:
    """The numbers one stored analysis lets the AI quote, by kind."""
    f = Facts(general=list(FIXED))
    f.general += _verdict_numbers(result.get("verdict"))
    f.general += _nums((result.get("region") or {}).get("name"))
    kind = result.get("kind")
    if kind == "trend":
        st = result.get("stats") or {}
        _stats_facts(st, f)
        s = result.get("series") or {}
        tested = s.get("tested") or {"labels": s.get("labels"), "values": s.get("values")}
        _record_years(f, s.get("labels"))
        _label_values(f, tested.get("labels"), tested.get("values"))
        _label_values(f, s.get("labels"), s.get("plot_values"))
        m = result.get("monthly") or {}
        _label_values(f, m.get("labels"), m.get("values"))
        cm = result.get("cell_map") or {}
        f.general += _nums([cm.get("n_cells"), cm.get("n_pass"), cm.get("n_raw_significant")])
    elif kind == "compare":
        c = result.get("comparison") or {}
        d = c.get("difference") or {}
        f.rates += _nums([d.get(k) for k in ("slope_per_decade", "ci_low_per_decade", "ci_high_per_decade",
                                              "ols_slope_per_decade", "min_detectable_per_decade")])  # fmt: skip
        f.pvalues += _nums([d.get(k) for k in ("p", "p_mk", "p_ols")])
        f.central += _nums([d.get("slope_per_decade"), d.get("ols_slope_per_decade")])
        f.general += _nums([c.get("n"), c.get("correlation")])
        for k in ("stats_a", "stats_b"):
            if c.get(k):
                _stats_facts(_with_per_decade(c[k]), f)
        _record_years(f, c.get("labels"))
        _label_values(f, c.get("labels"), c.get("a"))
        _label_values(f, c.get("labels"), c.get("b"))
        _label_values(f, c.get("labels"), c.get("diff"))
    else:  # related, month detail, scan, projections...: their own small summaries
        skip = {"series", "monthly", "cell_map", "geometry", "provenance", "data", "request", "variable",
                "region", "labels", "t", "values", "a", "b", "lags", "months"}  # fmt: skip

        def walk(o, key=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in skip:
                        continue
                    if k in ("p", "p_value", "p_adjusted", "p_mk", "p_ols"):
                        f.pvalues += _nums(v)
                    walk(v, k)
            elif isinstance(o, list):
                if len(o) <= 12:
                    for v in o:
                        walk(v, key)
            else:
                f.general.extend(_nums(o))

        walk(result)
    f.general += f.rates + f.pvalues
    return f


def add_ratios(f: Facts) -> None:
    """'N times faster': the ratios of the cited best-estimate rates (Sen and least squares)."""
    rates = [abs(r) for r in f.central if r and math.isfinite(r)]
    f.ratios = [a / b for a in rates for b in rates if b > 0 and a / b > 1.0]


# --------------------------------------------------------------------------------------
# Direction words
# --------------------------------------------------------------------------------------

UP = {
    "en": ["rising", "rises", "rose", "risen", "rise", "increasing", "increases", "increased", "warming",
           "warmed", "warmer", "hotter", "heating", "wetter", "greening", "growing", "grew", "grown",
           "upward", "gaining", "gained", "higher", "heavier", "climbing", "climbed", "going up", "went up",
           "gone up", "expanding"],
    "es": ["subiendo", "sube", "subió", "subido", "aumentando", "aumenta", "aumentó", "aumentado",
           "calentando", "calentado", "calentamiento", "más cálido", "más cálida", "más cálidos",
           "más cálidas", "más caliente", "más calientes", "más húmedo", "más húmeda", "reverdecimiento",
           "creciendo", "crece", "creciente", "al alza", "en aumento"],
}  # fmt: skip
DOWN = {
    "en": ["falling", "falls", "fell", "fallen", "decreasing", "decreases", "decreased", "declining",
           "declined", "decline", "cooling", "cooled", "cooler", "colder", "drier", "dryer", "drying",
           "browning", "shrinking", "shrank", "shrunk", "downward", "losing", "lost", "lower", "lighter",
           "dropping", "dropped", "going down", "went down", "gone down", "melting", "thinning"],
    "es": ["bajando", "baja", "bajó", "bajado", "disminuyendo", "disminuye", "disminuyó", "disminuido",
           "descendiendo", "desciende", "descendió", "descendido", "descenso", "cayendo", "cae", "cayó",
           "caído", "enfriando", "enfriado", "enfriamiento", "más frío", "más fría", "más fríos",
           "más frías", "más seco", "más seca", "secando", "a la baja", "en descenso", "derritiendo"],
}  # fmt: skip
NEGATIONS = {
    "en": ["not", "no", "n't", "never", "neither", "nor", "without", "hardly", "barely"],
    "es": ["no", "ni", "sin", "nunca", "tampoco"],
}
HEDGES = {
    "en": ["no clear", "not clear", "unclear", "not significant", "insignificant", "isn't significant",
           "is not significant", "could", "might", "may ", "possibly", "possible", "perhaps", "uncertain",
           "estimate", "range includes", "can't tell", "cannot tell", "can not tell", "inconclusive",
           "mixed", "not enough", "too short", "chance", "slight", "hint", "suggest", "appears", "seems",
           "if there is", "would need", "would take", "not yet", "noise", "ups and downs", "disagree"],
    "es": ["sin tendencia clara", "no está clar", "no es significativ", "podría", "puede", "posible",
           "quizá", "incierto", "estimación", "estimada", "el rango incluye", "no se puede", "mixta",
           "insuficiente", "azar", "ligera", "ligero", "parece", "sugiere", "harían falta", "haría falta",
           "todavía no", "altibajos", "no coinciden"],
}  # fmt: skip
# words for which way a temperature moves: they judge a temperature trend, not sea ice or rainfall
# ("Is the Arctic getting warmer?" said nothing about the sea ice trend it was checked against)
HEAT_WORDS = {
    "en": {"warming", "warmed", "warmer", "hotter", "heating", "cooling", "cooled", "cooler", "colder"},
    "es": {"calentando", "calentado", "calentamiento", "más cálido", "más cálida", "más cálidos", "más cálidas",
           "más caliente", "más calientes", "enfriando", "enfriado", "enfriamiento", "más frío", "más fría",
           "más fríos", "más frías"},
}  # fmt: skip
# a yes/no question asserts no direction; a why/how question can presuppose one, so it is still checked
YES_NO = re.compile(r"^(?:is|are|was|were|has|have|had|does|do|did|will|would|can|could|should|might|may)\b")
ES_WH = re.compile(r"^¿\s*(?:qué|por qué|cómo|cuándo|dónde|cuánt[oa]s?|cuál(?:es)?|quién(?:es)?)\b")


def _asks_yes_no(sentence: str) -> bool:
    s = sentence.strip().lower()
    if not s.endswith("?"):
        return False
    if s.startswith("¿"):
        return not ES_WH.match(s)
    return bool(YES_NO.match(s))


SIGNIFICANCE = re.compile(r"(?<!\w)(in)?(significant\w*|significativ\w*)")
# sentences about the pace of change or a difference judge those, not the trend itself
OTHER_CLAIMS = re.compile(r"accelerat|speed|pace|faster|slower|turning|differen|acelera|ritmo|diferencia")


@dataclass
class CheckResult:
    ok: bool
    unmatched: list[str] = field(default_factory=list)
    direction_errors: list[str] = field(default_factory=list)
    checked: int = 0


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


def _word_hits(low: str, words: list[str]) -> list[tuple[int, str]]:
    out = []
    for w in words:
        for m in re.finditer(rf"(?<![\w]){re.escape(w)}(?![\w])", low):
            out.append((m.start(), w))
    return out


# a negation ends where a new clause starts: "it shows the trend since 1980, not when warming began"
# negates "when", not "warming" (a correct answer was replaced by the plain verdict for this)
CLAUSE_WORDS = {
    "en": {"when", "where", "why", "how", "what", "which", "who", "whether", "if", "until", "because",
           "while", "though", "although"},
    "es": {"cuándo", "cuando", "dónde", "donde", "qué", "porque", "cómo", "si", "hasta", "aunque",
           "mientras"},
}  # fmt: skip


def _negated(low: str, pos: int, lang: str) -> bool:
    """A negation among the three words before position ``pos`` ("is not rising", "no ha subido"),
    unless a new clause starts between the two ("not when warming began")."""
    before = re.findall(r"[\w']+", low[:pos])[-3:]
    negs = NEGATIONS.get(lang, NEGATIONS["en"])
    stops = CLAUSE_WORDS.get(lang, CLAUSE_WORDS["en"])
    for w in reversed(before):
        if w in stops:
            return False
        if w in negs or w.endswith("n't"):
            return True
    return False


def _mentions(low: str, names: list[str]) -> bool:
    return any(nm and nm.lower() in low for nm in names)


def _labels_in(sentence: str, lang: str) -> list[str]:
    """Year and month labels named in a sentence: '2016', '2010-07' for 'July 2010' or '2010-07'."""
    low = normalise_text(sentence).lower()
    out = re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)-(0[1-9]|1[0-2])(?!\d)", low)
    labels = [f"{y}-{m}" for y, m in out]
    names = MONTHS.get(lang, []) + MONTHS["en"]
    for i, nm in enumerate(names):
        for m in re.finditer(rf"\b{nm}\b(?:\s+(?:de|of)\s+|\s+)(1[89]\d\d|20\d\d)\b", low):
            labels.append(f"{m.group(1)}-{(i % 12) + 1:02d}")
    labels += re.findall(r"(?<![\d.,])(1[89]\d\d|20\d\d)(?![\d.,])", low)
    return labels


def _context(text: str, found: FoundNumber) -> tuple[str, str]:
    t = normalise_text(text)
    return t[max(0, found.start - 12) : found.start].lower(), t[found.end : found.end + 60].lower()


RATE_TAIL = re.compile(r"per decade|a decade|each decade|/ ?decade|por década|cada década|/ ?década|par décennie|pro jahrzehnt")
YEAR_RATE_TAIL = re.compile(r"per year|a year|each year|/ ?yr|/ ?year|por año|al año|cada año")
# the unit of a change in a % quantity ("2.9 percentage points per decade") sits between number and tail
CHANGE_UNIT_HEAD = re.compile(r"^\s*(?:percentage[- ]points?|puntos? porcentuales?|pp\b|p\.\s?p\.)")
# the engine's rates are never relative: "2.9% per decade" misstates percentage points as a relative change
PERCENT_RATE = re.compile(r"^\s*%\s*(?:" + RATE_TAIL.pattern + r"|" + YEAR_RATE_TAIL.pattern + r")")
P_HEAD = re.compile(r"\bp\s*(?:-?value)?\s*(?:=|<|>|≤|≥|of|de|is|es)?\s*$")


def _check_number(n: FoundNumber, text: str, sentence_labels: list[str], f: Facts) -> bool:
    before, after = _context(text, n)
    if _is_ratio(text, n):
        return matches(n, f.ratios)
    if P_HEAD.search(before):
        return matches(n, f.pvalues + [0.05, 0.001, 0.01, 0.025])
    if n.decimals == 0 and 1800 <= abs(n.value) <= 2200 and not n.has_unit:
        return int(abs(n.value)) in f.years
    if PERCENT_RATE.match(after):
        return False
    after = CHANGE_UNIT_HEAD.sub("", after, count=1)
    if RATE_TAIL.search(after[:28]):
        return matches(n, f.rates)
    candidates = list(f.general)
    if YEAR_RATE_TAIL.search(after[:28]):
        candidates += [r / 10.0 for r in f.rates]
    for lab in sentence_labels:
        candidates += f.values.get(lab, [])
    return matches(n, candidates)


def check_text(
    text: str, allowed: Facts | list[float], directions: list[dict], lang: str = "en"
) -> CheckResult:
    """directions: [{"names": [...], "direction": "rising"|"falling"|"flat", "significant": bool}]"""
    facts = allowed if isinstance(allowed, Facts) else Facts.plain(allowed)
    if not facts.ratios:
        add_ratios(facts)
    res = CheckResult(ok=True)
    for sent in _sentences(text):
        labels = _labels_in(sent, lang)
        for n in find_numbers(sent, lang):
            if exempt(n, sent):
                continue
            res.checked += 1
            if not _check_number(n, sent, labels, facts):
                res.unmatched.append(n.text)
    _check_directions(text, directions, lang, res)
    res.ok = not res.unmatched and not res.direction_errors
    return res


def _check_directions(text: str, directions: list[dict], lang: str, res: CheckResult) -> None:
    trends = [d for d in directions if d.get("direction") in ("rising", "falling", "flat")]
    if not trends:
        return
    up = UP.get(lang, UP["en"])
    down = DOWN.get(lang, DOWN["en"])
    hedges = HEDGES.get(lang, HEDGES["en"])
    # with one trend cited (or all saying the same) every sentence is about it
    same = len({(d["direction"], bool(d.get("significant", True))) for d in trends}) == 1
    heat = HEAT_WORDS.get(lang, HEAT_WORDS["en"])
    for sent in _sentences(text):
        if _asks_yes_no(sent):
            continue
        low = sent.lower()
        about = [d for d in trends if _mentions(low, d.get("names", []))]
        if not about and same:
            about = trends[:1]
        ups = [(p, w, _negated(low, p, lang)) for p, w in _word_hits(low, up)]
        downs = [(p, w, _negated(low, p, lang)) for p, w in _word_hits(low, down)]
        hedged = any(h in low for h in hedges)
        other = bool(OTHER_CLAIMS.search(low))
        sig_claims = [
            (m.start(), m.group(0), bool(m.group(1)) or _negated(low, m.start(), lang))
            for m in SIGNIFICANCE.finditer(low)
        ]
        for d in about:
            direction = d["direction"]
            significant = bool(d.get("significant", True))
            if direction == "flat":
                continue
            u, dn = ups, downs
            if not d.get("temperature", True):  # warmer/cooler say nothing about this measurement
                u = [h for h in ups if h[1] not in heat]
                dn = [h for h in downs if h[1] not in heat]
            right, wrong = (u, dn) if direction == "rising" else (dn, u)
            said_wrong = [w for _, w, neg in wrong if not neg]
            said_right = [w for _, w, neg in right if not neg]
            denied_right = [w for _, w, neg in right if neg]
            if said_wrong and not said_right:
                res.direction_errors.append(f"{sent[:120]} (says {said_wrong[0]}, data say {direction})")
            elif significant and denied_right and not said_right:
                res.direction_errors.append(f"{sent[:120]} (says not {denied_right[0]}, but the {direction} trend is significant)")
            elif not significant and (said_right or said_wrong) and not hedged:
                w = (said_right or said_wrong)[0]
                res.direction_errors.append(f"{sent[:120]} (says {w} as a fact, but the tests found no clear trend)")
            if other:
                continue
            if not significant and any(not neg for _, _, neg in sig_claims) and not hedged:
                res.direction_errors.append(f"{sent[:120]} (calls it significant, but the tests did not)")
            denies = any(neg for _, _, neg in sig_claims) or "no clear trend" in low or "sin tendencia clara" in low
            if significant and denies:
                res.direction_errors.append(f"{sent[:120]} (says it is not significant, but the tests agree it is)")


def allowed_numbers(result: dict) -> list[float]:
    """The numbers one analysis lets the AI quote, as a flat list (for callers that need one)."""
    f = facts_from(result)
    return f.general + f.rates + f.pvalues + sorted(float(y) for y in f.years)
