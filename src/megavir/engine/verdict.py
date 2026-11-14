"""Plain-language verdicts built only from fixed templates (FR6).

No AI is involved: the same statistics always give the same words.  Every number in the
text is formatted here, and the formatted strings are returned alongside the text so the
AI number check (and the tests) can refer to exactly what was shown.
"""

from __future__ import annotations

import math

from megavir.catalog import Variable

from .stats import TrendStats

MINUS = "−"

TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        # headlines
        "head_sig": "{Name} in {place} has been {updown} since {start}: about {rate} {unit} per decade.",
        "head_nosig": "{Name} in {place}: no clear trend since {start}.",
        "head_mixed": "{Name} in {place}: the evidence is mixed.",
        "head_untestable": "{Name} in {place}: this record cannot be tested reliably.",
        "up": "rising",
        "down": "falling",
        # body
        "plain": "In short: {place} is {word}.",
        "range": "Best estimate {srate} {unit} per decade (95% range {lo} to {hi}), {period}.",
        "agree_sig": "Two independent tests agree that a change this steady is unlikely to be chance "
        "(Mann–Kendall p {p_mk}; least squares p {p_ols}), after allowing for how much each {step} "
        "resembles the one before.",
        "nosig": "The range includes no change at all, so the ups and downs could explain it "
        "(Mann–Kendall p {p_mk}; least squares p {p_ols}).",
        "mixed": "One test finds a trend and the other does not (Mann–Kendall p {p_mk}; least squares "
        "p {p_ols}), or they disagree on its direction, so we do not call it significant.",
        "untestable": "Each {step} is so similar to the one before ({r1}) that the record holds too few "
        "independent values to test. A longer record is needed.",
        "try_monthly": "Monthly values hold much more information: try the monthly anomalies view.",
        "effect": "Over the record the trend line moves {total} {unit_total}: {effect} next to the usual "
        "{step}-to-{step} scatter.",
        "need_more": "To tell a trend of this size from the natural ups and downs would take about "
        "{n_star} years of data: {more} more than the {span} years we have.",
        "enough_but_no": "A trend of this size would usually show up in a record this long, so if there "
        "is a real trend it is probably smaller than this estimate.",
        "fragile": "Handle with care: the trend is fragile. It changes direction {where}.",
        "robust": "The direction holds in both halves of the record and when any single year is left out.",
        "turning": "Exploratory clue: the change looks different before and after about {at} "
        "({before} then {after} {unit} per decade).",
        # caveats
        "cav_cause": "A trend is not a cause: this shows what changed, not why.",
        "cav_test": "TEST DATA: a small development sample, not a real result.",
        "cav_synthetic": "SYNTHETIC DATA: made-up numbers for software testing only.",
        "cav_coverage": "Parts of the region had no data in some months (lowest coverage {cov}).",
        "cav_seasonal": "Monthly values: each month is compared only with the same month in other years.",
        # compare
        "cmp_head_sig": "{Name}: {a} and {b} really are changing differently, by about {diff} {unit} per decade.",
        "cmp_head_nosig": "{Name}: no clear difference between the trends in {a} and {b}.",
        "cmp_body": "The test is run on the difference {a} minus {b}, so the ups and downs the two "
        "regions share cancel out. Difference {sdiff} {unit} per decade (95% range {lo} to {hi}; "
        "p {p}).",
        "cmp_mdd": "With this record, differences smaller than about {mdd} {unit} per decade cannot be "
        "detected.",
        "cmp_opposite": "The two trends point in opposite directions.",
        "step_year": "year",
        "step_month": "month",
        "since_season": "{season} only",
    },
    "es": {
        "head_sig": "{Name} en {place} ha estado {updown} desde {start}: alrededor de {rate} {unit} por década.",
        "head_nosig": "{Name} en {place}: sin tendencia clara desde {start}.",
        "head_mixed": "{Name} en {place}: la evidencia es mixta.",
        "head_untestable": "{Name} en {place}: este registro no se puede evaluar con fiabilidad.",
        "up": "subiendo",
        "down": "bajando",
        "plain": "En resumen: en {place} la tendencia es {word}.",
        "range": "Mejor estimación {srate} {unit} por década (rango del 95 %: {lo} a {hi}), {period}.",
        "agree_sig": "Dos pruebas independientes coinciden en que un cambio tan constante difícilmente es "
        "casualidad (Mann–Kendall p {p_mk}; mínimos cuadrados p {p_ols}), teniendo en cuenta cuánto se "
        "parece cada {step} al anterior.",
        "nosig": "El rango incluye la ausencia de cambio, así que los altibajos podrían explicarlo "
        "(Mann–Kendall p {p_mk}; mínimos cuadrados p {p_ols}).",
        "mixed": "Una prueba encuentra tendencia y la otra no (Mann–Kendall p {p_mk}; mínimos cuadrados "
        "p {p_ols}), o no coinciden en la dirección, así que no la llamamos significativa.",
        "untestable": "Cada {step} se parece tanto al anterior ({r1}) que el registro tiene muy pocos "
        "valores independientes. Hace falta un registro más largo.",
        "try_monthly": "Los valores mensuales contienen mucha más información: pruebe la vista de anomalías mensuales.",
        "effect": "A lo largo del registro la línea de tendencia se mueve {total} {unit_total}: un cambio "
        "{effect} frente a la dispersión habitual.",
        "need_more": "Para distinguir una tendencia de este tamaño de los altibajos naturales harían falta "
        "unos {n_star} años de datos: {more} más que los {span} que tenemos.",
        "enough_but_no": "Una tendencia de este tamaño normalmente se vería en un registro así de largo; "
        "si hay una tendencia real, probablemente es menor que esta estimación.",
        "fragile": "Con cautela: la tendencia es frágil. Cambia de dirección {where}.",
        "robust": "La dirección se mantiene en ambas mitades del registro y al quitar cualquier año.",
        "turning": "Pista exploratoria: el cambio parece distinto antes y después de {at} "
        "({before} y luego {after} {unit} por década).",
        "cav_cause": "Una tendencia no es una causa: muestra qué cambió, no por qué.",
        "cav_test": "DATOS DE PRUEBA: una muestra pequeña de desarrollo, no un resultado real.",
        "cav_synthetic": "DATOS SINTÉTICOS: números inventados solo para probar el software.",
        "cav_coverage": "Partes de la región no tuvieron datos algunos meses (cobertura mínima {cov}).",
        "cav_seasonal": "Valores mensuales: cada mes se compara solo con el mismo mes de otros años.",
        "cmp_head_sig": "{Name}: {a} y {b} realmente cambian de forma distinta, unos {diff} {unit} por década.",
        "cmp_head_nosig": "{Name}: sin diferencia clara entre las tendencias de {a} y {b}.",
        "cmp_body": "La prueba se hace sobre la diferencia {a} menos {b}, así que los altibajos comunes se "
        "cancelan. Diferencia {sdiff} {unit} por década (rango del 95 %: {lo} a {hi}; p {p}).",
        "cmp_mdd": "Con este registro no se pueden detectar diferencias menores de unos {mdd} {unit} por década.",
        "cmp_opposite": "Las dos tendencias van en direcciones opuestas.",
        "step_year": "año",
        "step_month": "mes",
        "since_season": "solo {season}",
    },
}

EFFECT_WORDS = {
    "en": {"small": "small", "moderate": "moderate", "large": "large", "very large": "very large"},
    "es": {"small": "pequeño", "moderate": "moderado", "large": "grande", "very large": "muy grande"},
}

LANGUAGES = tuple(TEMPLATES)


# --------------------------------------------------------------------------------------
# Number formatting (deterministic, shared with the AI number check)
# --------------------------------------------------------------------------------------


def fmt_num(x: float, sig: int = 2, max_decimals: int = 4, lang: str = "en") -> str:
    if x is None or not math.isfinite(x):
        return "∞" if x and x > 0 else "−∞"
    if x == 0:
        return "0"
    mag = math.floor(math.log10(abs(x)))
    dec = min(max_decimals, max(0, sig - 1 - mag))
    s = f"{abs(x):,.{dec}f}"
    if lang == "es":
        s = s.replace(",", " ").replace(".", ",")
    return (MINUS if x < 0 else "") + s


def fmt_signed(x: float, sig: int = 2, lang: str = "en") -> str:
    s = fmt_num(x, sig, lang=lang)
    return s if s.startswith(MINUS) or s == "0" else "+" + s


def fmt_p(p: float, lang: str = "en") -> str:
    if p < 0.001:
        return "< " + ("0,001" if lang == "es" else "0.001")
    return "= " + fmt_num(p, sig=2, max_decimals=4, lang=lang)


def fmt_pct(x: float) -> str:
    return f"{round(100 * x):d}%"


# --------------------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------------------


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def data_caveat(data_kind: str, lang: str) -> str | None:
    t = TEMPLATES[lang]
    return {"test": t["cav_test"], "synthetic": t["cav_synthetic"]}.get(data_kind)


def trend_verdict(
    st: TrendStats,
    var: Variable,
    place: str,
    unit: str,
    season: str | None = None,
    lang: str = "en",
    data_kind: str = "real",
    min_coverage: float | None = None,
) -> dict:
    """Return {"status", "headline", "sentences", "caveats", "shown"} for one trend."""
    if lang not in TEMPLATES:
        lang = "en"
    t = TEMPLATES[lang]
    per_dec = 10.0
    rate = st.sen.slope * per_dec
    lo, hi = st.sen.ci_low * per_dec, st.sen.ci_high * per_dec
    start = int(math.floor(st.first))
    end = int(math.floor(st.last))
    step = t["step_month"] if st.per_year == 12 else t["step_year"]
    period = f"{start}–{end}" + (", " + t["since_season"].format(season=season) if season else "")
    shown = {
        "rate": fmt_num(abs(rate), lang=lang),
        "srate": fmt_signed(rate, lang=lang),
        "lo": fmt_signed(lo, lang=lang),
        "hi": fmt_signed(hi, lang=lang),
        "p_mk": fmt_p(st.mk.p, lang),
        "p_ols": fmt_p(st.ols.p, lang),
        "start": str(start),
        "end": str(end),
    }
    common = {"Name": _cap(var.name), "place": place, "unit": unit, "period": period, "step": step, **shown}
    up = st.sen.slope > 0
    word = var.rising_words[0] if up else var.rising_words[1]
    updown = t["up"] if up else t["down"]
    sentences: list[str] = []

    if not st.ols.testable:
        status = "not_testable"
        headline = t["head_untestable"].format(**common)
        shown["r1"] = fmt_num(st.ols.r1, lang=lang)
        sentences.append(t["untestable"].format(r1=f"r₁ = {shown['r1']}", step=step))
        if st.per_year == 1:
            sentences.append(t["try_monthly"])
    elif st.significant:
        status = "significant"
        headline = t["head_sig"].format(updown=updown, **common)
        sentences.append(t["plain"].format(place=place, word=word))
        sentences.append(t["range"].format(**common))
        sentences.append(t["agree_sig"].format(**common))
    elif (st.mk.p < st.alpha) != (st.ols.p < st.alpha) or (
        st.mk.p < st.alpha and st.ols.p < st.alpha and not st.agree
    ):
        status = "tests_disagree"
        headline = t["head_mixed"].format(**common)
        sentences.append(t["range"].format(**common))
        sentences.append(t["mixed"].format(**common))
    else:
        status = "not_significant"
        headline = t["head_nosig"].format(**common)
        sentences.append(t["range"].format(**common))
        sentences.append(t["nosig"].format(**common))

    if st.ols.testable:
        span = st.last - st.first
        total = abs(st.sen.slope) * span
        shown["total"] = fmt_num(total, lang=lang)
        sentences.append(
            t["effect"].format(
                total=shown["total"], unit_total=unit, effect=EFFECT_WORDS[lang][st.effect_label], step=step
            )
        )
    if status in ("not_significant", "tests_disagree") and math.isfinite(st.years_needed):
        span_years = int(round(st.last - st.first + 1.0 / st.per_year))
        if st.years_more > 0:
            shown["n_star"] = str(int(math.ceil(st.years_needed)))
            shown["more"] = str(int(st.years_more))
            shown["span"] = str(span_years)
            sentences.append(
                t["need_more"].format(n_star=shown["n_star"], more=shown["more"], span=shown["span"])
            )
        else:
            sentences.append(t["enough_but_no"])
    if status == "significant":
        if st.robustness.fragile:
            failed = [c["check"] for c in st.robustness.checks if not c["keeps_sign"]]
            where = _join_checks(failed[:3], lang)
            sentences.append(t["fragile"].format(where=where))
        else:
            sentences.append(t["robust"])
    if st.turning and st.turning.get("preferred"):
        shown["turning_at"] = str(int(st.turning["at"]))
        sentences.append(
            t["turning"].format(
                at=shown["turning_at"],
                before=fmt_signed(st.turning["slope_before"] * per_dec, lang=lang),
                after=fmt_signed(st.turning["slope_after"] * per_dec, lang=lang),
                unit=unit,
            )
        )

    caveats = [t["cav_cause"], var.caveat]
    if st.seasonal_test:
        caveats.append(t["cav_seasonal"])
    if min_coverage is not None and min_coverage < 0.95:
        caveats.append(t["cav_coverage"].format(cov=fmt_pct(min_coverage)))
    dc = data_caveat(data_kind, lang)
    if dc:
        caveats.insert(0, dc)
    return {
        "status": status,
        "direction": st.direction,
        "headline": headline,
        "sentences": sentences,
        "caveats": caveats,
        "shown": shown,
        "lang": lang,
    }


_CHECK_WORDS = {
    "es": {
        "first half": "en la primera mitad",
        "second half": "en la segunda mitad",
        "without first and last years": "sin el primer y el último año",
        "without": "sin",
    }
}


def _join_checks(names: list[str], lang: str) -> str:
    if lang == "en":
        words = [n if n.startswith("without") else f"in the {n}" for n in names]
        return ", ".join(words[:-1]) + (" and " if len(words) > 1 else "") + words[-1]
    m = _CHECK_WORDS.get(lang, {})
    words = []
    for n in names:
        if n in m:
            words.append(m[n])
        elif n.startswith("without "):
            words.append(m.get("without", "without") + n[len("without") :])
        else:
            words.append(n)
    return ", ".join(words[:-1]) + (" y " if len(words) > 1 else "") + words[-1]


def compare_verdict(
    cmp: dict,
    var: Variable,
    name_a: str,
    name_b: str,
    unit: str,
    lang: str = "en",
    data_kind: str = "real",
) -> dict:
    t = TEMPLATES.get(lang, TEMPLATES["en"])
    d = cmp["difference"]
    shown = {
        "diff": fmt_num(abs(d["slope_per_decade"]), lang=lang),
        "sdiff": fmt_signed(d["slope_per_decade"], lang=lang),
        "lo": fmt_signed(d["ci_low_per_decade"], lang=lang),
        "hi": fmt_signed(d["ci_high_per_decade"], lang=lang),
        "p": fmt_p(d["p"], lang),
        "mdd": fmt_num(d["min_detectable_per_decade"], lang=lang),
    }
    common = {"Name": _cap(var.name), "a": name_a, "b": name_b, "unit": unit, **shown}
    status = "significant" if d["significant"] else "not_significant"
    headline = t["cmp_head_sig" if d["significant"] else "cmp_head_nosig"].format(**common)
    sentences = [t["cmp_body"].format(**common), t["cmp_mdd"].format(**common)]
    if cmp.get("opposite"):
        sentences.append(t["cmp_opposite"])
    caveats = [t["cav_cause"], var.caveat]
    dc = data_caveat(data_kind, lang)
    if dc:
        caveats.insert(0, dc)
    return {
        "status": status,
        "headline": headline,
        "sentences": sentences,
        "caveats": caveats,
        "shown": shown,
        "lang": lang,
    }
