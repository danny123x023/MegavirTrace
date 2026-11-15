"""Run a detective case: every step goes through the engine, and the findings are written from the
numbers it returns (never from the story).

A step's evidence is what the page draws (a chart with the event marked) and its finding is one or
two sentences built from templates, in English or Spanish.  Results are kept in the analysis cache
like any other analysis, keyed by the case, the language, the data versions and the engine version.
"""

from __future__ import annotations

import math

import numpy as np

from megavir.api import service
from megavir.api.service import AnalysisError
from megavir.catalog import DATASETS, VARIABLES
from megavir.engine.aggregate import month_zscore
from megavir.engine.verdict import change_unit, fmt_num, fmt_signed
from megavir.places.presets import PRESETS
from megavir.store import active_versions

from .catalog import BY_ID, CASES, CASES_REV, Case, Step

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"],
}  # fmt: skip
SEASONS = {
    "en": {"DJF": "Dec–Feb", "MAM": "Mar–May", "JJA": "Jun–Aug", "SON": "Sep–Nov"},
    "es": {"DJF": "dic–feb", "MAM": "mar–may", "JJA": "jun–ago", "SON": "sep–nov"},
}
# quantities that start at zero, where "times the usual" means something
RATIO_VARS = {"rainfall", "downpour", "fire_carbon", "no2", "aerosols"}

T = {
    "en": {
        "month": "{when} in {place}: {value}, against a usual {mean} for {month}. That is {z} standard deviations "
        "{dir} normal: {rank} of {n} {months}.",
        "above": "above",
        "below": "below",
        "ratio_up": " About {x} times the usual amount.",
        "ratio_down": " About {x}% below the usual amount.",
        "highest": "the highest",
        "lowest": "the lowest",
        "nth_high": "the {k} highest",
        "nth_low": "the {k} lowest",
        "rank": "{label} is {rank} of {n} {units}.",
        "since_none": " None since has been {more}.",
        "since_some": " Since then {k} {was} {more}: {which}.",
        "more_high": "higher",
        "more_low": "lower",
        "more_high_n": "higher",
        "more_low_n": "lower",
        "was1": "was",
        "wasn": "were",
        "years": "years",
        "seasons": "{s} seasons",
        "months_unit": "months",
        "and": "and",
        "missing": "No data for {when} in this record.",
    },
    "es": {
        "month": "{When} en {place}: {value}, frente a {mean} habituales en {month}. Son {z} desviaciones típicas "
        "{dir} de lo normal: {rank} de {n} meses de {month}.",
        "above": "por encima",
        "below": "por debajo",
        "ratio_up": " Unas {x} veces lo habitual.",
        "ratio_down": " Alrededor de un {x}% menos de lo habitual.",
        "highest": "el valor más alto",
        "lowest": "el valor más bajo",
        "nth_high": "el {k} valor más alto",
        "nth_low": "el {k} valor más bajo",
        "rank": "{label} es {rank} de {n} {units}.",
        "since_none": " Ninguno posterior ha sido {more}.",
        "since_some": " Desde entonces, {k} {was} {more}: {which}.",
        "more_high": "más alto",
        "more_low": "más bajo",
        "more_high_n": "más altos",
        "more_low_n": "más bajos",
        "was1": "ha sido",
        "wasn": "han sido",
        "years": "años",
        "seasons": "temporadas {s}",
        "months_unit": "meses",
        "and": "y",
        "missing": "No hay datos de {when} en este registro.",
    },
}


def _lang(lang: str) -> str:
    return lang if lang in T else "en"


def ordinal(k: int, lang: str) -> str:
    if lang == "es":
        return f"{k}.º"
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def label_text(label: str, lang: str) -> str:
    """'2003 JJA' -> '2003 (Jun–Aug)', '2022-04' -> 'April 2022', '2016' -> '2016'."""
    if " " in label:
        y, s = label.split(" ", 1)
        return f"{y} ({SEASONS[lang].get(s, s)})"
    if len(label) == 7 and label[4] == "-":
        y, m = int(label[:4]), int(label[5:])
        return f"{MONTHS[lang][m - 1]} {'de ' if lang == 'es' else ''}{y}"
    return label


def _join(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {T[lang]['and']} " + items[-1]


def _value(x: float, units: str, lang: str) -> str:
    return f"{fmt_num(x, 3, lang=lang)} {units}".strip()


def _rank_phrase(rank: int, extreme: str, lang: str) -> str:
    t = T[lang]
    if rank == 1:
        return t["highest"] if extreme == "high" else t["lowest"]
    return (t["nth_high"] if extreme == "high" else t["nth_low"]).format(k=ordinal(rank, lang))


def _region(spec: dict, lang: str) -> dict:
    """A case region as the engine takes it (box names are given per language)."""
    if "bbox" in spec:
        name = spec.get("name") or {}
        return {"bbox": spec["bbox"], "name": name.get(lang) or name.get("en")}
    return {"place": spec["place"]}


def _variable(var_id: str, lang: str) -> dict:
    v = VARIABLES[var_id]
    d = DATASETS[v.dataset]
    return {"id": v.id, "name": v.local(lang)["name"], "units": v.units, "product": d.product, "doi": d.doi}


def _explore_link(step: Step) -> dict:
    """Query parameters that reopen the same analysis on the Explore page."""
    q: dict = {"v": step.variable}
    if "place" in step.region:
        q["place"] = step.region["place"]
        preset = PRESET_BY_ID.get(step.region["place"])
        if preset:
            q["label"] = preset["name"]
    else:
        q["bbox"] = ",".join(str(x) for x in step.region["bbox"])
    mode = step.mode or VARIABLES[step.variable].default_mode
    if step.kind != "month":
        q["mode"] = mode
        if mode == "season" and step.season:
            q["season"] = step.season
        if step.start:
            q["start"] = step.start
        if step.end:
            q["end"] = step.end
    return q


# --------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------


def run_month(conn, step: Step, lang: str) -> dict:
    """One month against the same calendar month of every year: how unusual, and its rank."""
    region = service.resolve_region(conn, _region(step.region, lang), lang)
    rd = service.regional_monthly(conn, step.variable, region)
    var = VARIABLES[step.variable]
    # the same values the engine's month test uses: every finite month of that calendar month
    same = (rd.months % 12 + 1 == step.month) & np.isfinite(rd.values)
    yrs = [int(y) for y in rd.months[same] // 12]
    vals = [float(v) for v in rd.values[same]]
    when_en = label_text(f"{step.year}-{step.month:02d}", lang)
    z = month_zscore(rd.months, rd.values, step.year, step.month)
    if z is None or step.year not in yrs:
        raise AnalysisError(T[lang]["missing"].format(when=when_en))
    above = z["z"] >= 0
    rank = z["rank_from_highest"] if above else z["of"] - z["rank_from_highest"] + 1
    t = T[lang]
    month_name = MONTHS[lang][step.month - 1]
    finding = t["month"].format(
        when=when_en,
        When=when_en[:1].upper() + when_en[1:],
        place=region.name,
        value=_value(z["value"], var.units, lang),
        mean=_value(z["mean"], var.units, lang),
        month=month_name,
        z=fmt_num(abs(z["z"]), 2, lang=lang),
        dir=t["above"] if above else t["below"],
        rank=_rank_phrase(rank, "high" if above else "low", lang),
        n=z["of"],
        months={"January": "Januaries", "February": "Februaries"}.get(month_name, month_name + "s"),
    )
    if step.variable in RATIO_VARS and z["mean"] > 0 and z["value"] >= 0:
        ratio = z["value"] / z["mean"]
        if ratio >= 1.5:
            finding += t["ratio_up"].format(x=fmt_num(ratio, 2, lang=lang))
        elif ratio <= 0.8:
            finding += t["ratio_down"].format(x=round(100 * (1 - ratio)))
    return {
        "finding": finding,
        "numbers": {
            "value": z["value"],
            "mean": z["mean"],
            "z": z["z"],
            "rank": rank,
            "of": z["of"],
            "extreme": "high" if above else "low",
        },  # fmt: skip
        "chart": {
            "kind": "month",
            "title": f"{month_name[:1].upper() + month_name[1:]} · {region.name}",
            "labels": [str(y) for y in yrs],
            "t": [float(y) for y in yrs],
            "series": [{"key": "value", "values": vals}],
            "highlight": [yrs.index(step.year)],
            "mean": float(np.mean(vals)),
            "units": var.units,
        },
        "region": region.name,
        "analysis_id": None,
    }


MONTH_NAMES = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"],
}  # fmt: skip


def partial_year_note(labels: list[str], last_month: str | None, mode: str, lang: str) -> tuple[str | None, str]:
    """(label, note) for a last year that is still under way, e.g. ("2026", " (to October)")."""
    if mode not in ("annual", "monthly", "raw") or not labels or not last_month or last_month.endswith("-12"):
        return None, ""
    year, month = last_month[:4], int(last_month[5:7])
    if str(labels[-1])[:4] != year:
        return None, ""
    name = MONTH_NAMES.get(lang, MONTH_NAMES["en"])[month - 1]
    return str(labels[-1]), (f" (hasta {name})" if lang == "es" else f" (to {name})")


def _highlight_text(
    labels: list[str], values: list, step: Step, units_word: str, lang: str, partial: tuple[str | None, str] = (None, "")
) -> str:
    """Where each marked label ranks in the series, and whether later values went past it.

    A last year still under way is named as such ("2026 (to October)"), so a ranking never
    presents it as a whole year."""
    t = T[lang]

    def label_text_p(x: str) -> str:
        return label_text(x, lang) + (partial[1] if partial[0] is not None and x == partial[0] else "")

    pairs = [(lab, v) for lab, v in zip(labels, values, strict=True) if v is not None]
    if not pairs:
        return ""
    high = step.extreme == "high"
    out = []
    for h in step.highlight:
        idx = next((i for i, (lab, _) in enumerate(pairs) if lab == h), None)
        if idx is None:
            continue
        v = pairs[idx][1]
        better = [lab for lab, w in pairs if (w > v if high else w < v)]
        rank = len(better) + 1
        out.append(
            t["rank"].format(
                label=label_text_p(h),
                rank=_rank_phrase(rank, step.extreme, lang),
                n=len(pairs),
                units=units_word,
            )
        )
        if len(step.highlight) == 1 and rank <= 5:
            later = [lab for lab, w in pairs[idx + 1 :] if (w > v if high else w < v)]
            more = t["more_high"] if high else t["more_low"]
            if not later:
                out[-1] += t["since_none"].format(more=more)
            else:
                out[-1] += t["since_some"].format(
                    k=("one" if lang == "en" else "uno") if len(later) == 1 else len(later),
                    was=t["was1"] if len(later) == 1 else t["wasn"],
                    more=more if len(later) == 1 else t["more_high_n" if high else "more_low_n"],
                    which=_join([label_text_p(x) for x in later], lang),
                )
    return " ".join(out)


def _per_year(per_decade):
    """A stored per-decade rate as a rate per year; an unbounded range end is stored as "inf"/"-inf"."""
    if isinstance(per_decade, str):
        return per_decade  # "inf" or "-inf": the chart draws no band on that side
    return None if per_decade is None else per_decade / 10


def run_trend_step(conn, step: Step, lang: str) -> dict:
    r = service.run_trend(
        conn,
        {
            "variable": step.variable,
            "region": _region(step.region, lang),
            "mode": step.mode,
            "season": step.season,
            "start_year": step.start,
            "end_year": step.end,
            "cell_map": False,
            "lang": lang,
        },
    )
    s = r["series"]
    t = T[lang]
    units_word = {"annual": t["years"], "season": t["seasons"].format(s=SEASONS[lang].get(s["season"] or "", "")),
                  "monthly": t["months_unit"]}.get(s["mode"], t["years"])  # fmt: skip
    finding = r["verdict"]["headline"]
    partial = partial_year_note(s.get("tested", s)["labels"], (r.get("data") or {}).get("last_month"), s["mode"], lang)
    extra = _highlight_text(s["labels"], s["values"], step, units_word, lang, partial)
    pd = r["stats"]["per_decade"]
    labels = s["labels"]
    return {
        "finding": (finding + " " + extra).strip(),
        "numbers": {
            "per_decade": pd["sen"],
            "low": pd["sen_low"],
            "high": pd["sen_high"],
            "units": r["units"],
            "status": r["verdict"]["status"],
            "significant": bool(r["stats"]["significant"]),
        },  # fmt: skip
        "chart": {
            "kind": "trend",
            "title": r["variable"]["name"] if lang == "en" else VARIABLES[step.variable].local(lang)["name"],
            "labels": labels,
            "t": s["t"],
            "series": [{"key": "value", "values": s["plot_values"]}],
            "trend": {"line": s["trend_line"], "low": _per_year(pd["sen_low"]), "high": _per_year(pd["sen_high"])},
            "highlight": [labels.index(h) for h in step.highlight if h in labels],
            "units": r["units"],
            "per_decade_label": f"{fmt_signed(pd['sen'], 2, lang=lang)} {change_unit(r['units'], lang, short=True)}",
        },
        "region": r["region"]["name"],
        "analysis_id": r["id"],
    }


def run_compare_step(conn, step: Step, lang: str) -> dict:
    r = service.run_compare(
        conn,
        {
            "variable": step.variable,
            "region_a": _region(step.region, lang),
            "region_b": _region(step.region_b or {}, lang),
            "mode": step.mode,
            "season": step.season,
            "start_year": step.start,
            "end_year": step.end,
            "lang": lang,
        },
    )
    c = r["comparison"]
    d = c["difference"]
    return {
        "finding": r["verdict"]["headline"],
        "numbers": {
            "difference_per_decade": d["slope_per_decade"],
            "low": d["ci_low_per_decade"],
            "high": d["ci_high_per_decade"],
            "significant": bool(d["significant"]),
            "units": r["units"],
        },  # fmt: skip
        "chart": {
            "kind": "compare",
            "title": r["variable"]["name"] if lang == "en" else VARIABLES[step.variable].local(lang)["name"],
            "labels": c["labels"],
            "t": c["t"],
            "series": [
                {"key": "a", "label": r["region_a"]["name"], "values": c["a"]},
                {"key": "b", "label": r["region_b"]["name"], "values": c["b"]},
            ],
            "highlight": [],
            "units": r["units"],
        },
        "region": f"{r['region_a']['name']} · {r['region_b']['name']}",
        "analysis_id": r["id"],
    }


RUNNERS = {"month": run_month, "trend": run_trend_step, "compare": run_compare_step}


def run_step(conn, step: Step, lang: str) -> dict:
    out = {
        "kind": step.kind,
        "title": step.title,
        "look": step.look,
        "variable": _variable(step.variable, lang),
        "explore": _explore_link(step),
    }
    try:
        out.update(RUNNERS[step.kind](conn, step, lang))
    except AnalysisError as e:
        out["error"] = str(e)
    return out


# --------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------


def _versions(conn, case: Case) -> list[int]:
    versions = active_versions(conn)
    return sorted({versions[s.variable].id for s in case.steps if s.variable in versions})


def _data_kind(conn, case: Case) -> str:
    """'real' when every variable of the case is served from real NASA data."""
    versions = active_versions(conn)
    kinds = {versions[s.variable].kind if s.variable in versions else "missing" for s in case.steps}
    return kinds.pop() if len(kinds) == 1 else "mixed"


PRESET_BY_ID = {f"preset:{p['id']}": p for p in PRESETS}


def outlines(case: Case, lang: str = "en") -> list[dict]:
    """Every region the case looks at, once, with a box for the map."""
    out: dict[str, dict] = {}
    for st in case.steps:
        for r in (st.region, st.region_b):
            if not r:
                continue
            if "place" in r:
                p = PRESET_BY_ID.get(r["place"])
                if p:
                    out[r["place"]] = {"label": p["name"], "bbox": p["bbox"]}
            else:
                key = ",".join(map(str, r["bbox"]))
                out[key] = {
                    "label": (r.get("name") or {}).get(lang) or (r.get("name") or {}).get("en", ""),
                    "bbox": r["bbox"],
                }
    return list(out.values())


def describe(case: Case, lang: str = "en") -> dict:
    return {
        "id": case.id,
        "title": case.title,
        "theme": case.theme,
        "kind": case.kind,
        "when": case.when,
        "where": case.where,
        "story": case.story,
        "question": case.question,
        "takeaway": case.takeaway,
        "skills": list(case.skills),
        "n_steps": len(case.steps),
        "variables": [_variable(v, lang) for v in dict.fromkeys(s.variable for s in case.steps)],
        "regions": outlines(case, lang),
    }


def run_case(conn, case_id: str, lang: str = "en", use_cache: bool = True) -> dict:
    case = BY_ID.get(case_id)
    if not case:
        raise AnalysisError(f"unknown case {case_id!r}")
    lang = _lang(lang)
    req = {"case": case.id, "lang": lang, "rev": CASES_REV}
    fid = service.fingerprint("case", req, _versions(conn, case))
    if use_cache and (hit := service.cached(conn, fid)):
        return hit
    steps = [run_step(conn, s, lang) for s in case.steps]
    result = {
        **describe(case, lang),
        "data_kind": _data_kind(conn, case),
        "steps": steps,
        "key": case.key,
        "lang": lang,
    }
    result = _finite(result)
    if not any("error" in s for s in steps):  # a step that failed is retried next time
        service.store(conn, fid, "case", req, _versions(conn, case), result)
    return result


def key_evidence(result: dict) -> dict | None:
    """The finding and a small chart of the case's key step, for the case card."""
    steps = result["steps"]
    step = steps[result["key"]] if result["key"] < len(steps) else None
    if not step or "error" in step:
        step = next((s for s in steps if "error" not in s), None)
    if not step:
        return None
    ch = step["chart"]
    return {
        "finding": step["finding"],
        "title": step["title"],
        "chart": {k: ch[k] for k in ("kind", "labels", "series", "highlight", "units")},
    }


def list_cases(conn, lang: str = "en") -> list[dict]:
    out = []
    for case in CASES:
        r = run_case(conn, case.id, lang)
        out.append({**describe(case, lang), "data_kind": r["data_kind"], "evidence": key_evidence(r)})
    return out


def _finite(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_finite(v) for v in obj]
    return obj
